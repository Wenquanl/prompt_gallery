# gallery/ai_providers.py
import os
import base64
import fal_client
from openai import OpenAI

class BaseAIProvider:
    """AI 生图提供商的基类（接口定义）"""
    def generate(self, model_config, api_args, base_image_files=None):
        """
        统一接口
        :param model_config: AI_STUDIO_CONFIG 中的模型配置字典
        :param api_args: 组装好的参数字典 (包含 prompt, steps, size 等)
        :param base_image_files: 上传的参考图文件对象列表
        :return: 生成的图片 URL 列表 (List[str])
        """
        raise NotImplementedError("子类必须实现 generate 方法")


class FalAIProvider(BaseAIProvider):
    """当前正在使用的 Fal.ai 接口适配器"""
    def generate(self, model_config, api_args, base_image_files=None):
        endpoint = model_config['endpoint']
        category_id = model_config['category']
        os.environ["FAL_KEY"] = os.getenv("FAL_KEY", "")

        # 1. 处理上传参考图
        uploaded_image_urls = []
        if base_image_files:
            for file in base_image_files:
                # 注意：如果未来其他平台不需要预上传图片，只需在其他适配器里修改这部分逻辑即可
                url = fal_client.upload(file.read(), file.content_type)
                uploaded_image_urls.append(url)
                
            if category_id == 'i2i':
                api_args['image_url'] = uploaded_image_urls[0]
            else:
                api_args['image_urls'] = uploaded_image_urls

        # 2. 调用生成接口
        result = fal_client.subscribe(endpoint, arguments=api_args)
        
        # 3. 统一返回格式：提取并返回 URL 字符串列表
        gen_images = result.get('images', [])
        return [img.get('url') for img in gen_images if img.get('url')]

class VolcengineProvider(BaseAIProvider):
    def generate(self, model_config, api_args, base_image_files=None):
        client = OpenAI(
            base_url="https://ark.cn-beijing.volces.com/api/v3",
            api_key=os.getenv('ARK_API_KEY')
        )

        model_endpoint = model_config['endpoint']
        prompt = api_args.get('prompt', '')
        size = api_args.get('image_size', '2K')
        max_images = int(api_args.get('max_images', 1))

        # 1. 基础特有参数：水印
        extra_body = {
            "watermark": api_args.get('watermark', False)
        }

        # 2. 组图逻辑：只有明确要求多图时，才开启 sequential_image_generation
        if max_images > 1:
            extra_body["sequential_image_generation"] = "auto"
            extra_body["sequential_image_generation_options"] = {"max_images": max_images}

        # 3. 处理参考垫图 (Base64)
        encoded_images = []
        if base_image_files:
            for file in base_image_files:
                # 获取文件的 MIME 类型 (例如 'image/png', 'image/jpeg')
                # Django 的 UploadedFile 对象带有 content_type 属性
                mime_type = getattr(file, 'content_type', 'image/jpeg')
                
                # 读取并转为 Base64
                file_content = file.read()
                base64_str = base64.b64encode(file_content).decode('utf-8')
                
                # 【核心修复】：拼接成标准的 Data URL 格式，这被视为合法的 URL
                data_url = f"data:{mime_type};base64,{base64_str}"
                encoded_images.append(data_url)
                
            if len(encoded_images) == 1:
                extra_body["image"] = encoded_images[0] # 单图模式传字符串
            elif len(encoded_images) > 1:
                extra_body["image"] = encoded_images    # 多图模式传列表

        # 4. 极速模式支持 (仅限 Seedream 4.0)
        optimize_mode = api_args.get('optimize_prompt_mode')
        if optimize_mode == 'fast':
            extra_body["optimize_prompt_options"] = {"mode": "fast"}

        # 5. 拼装核心请求体
        request_payload = {
            "model": model_endpoint,
            "prompt": prompt,
            "size": size,
            "response_format": "url",
        }

        # 6. 输出格式支持 (仅限 5.0 lite 支持配置)
        if 'output_format' in api_args:
            request_payload["output_format"] = api_args['output_format']

        # 7. 联网搜索支持 (仅限 5.0 lite)
        if api_args.get('enable_web_search'):
            extra_body["tools"] = [{"type": "web_search"}]
        request_payload["extra_body"] = extra_body
        # ==================================
        # 调用官方接口
        # ==================================
        response = client.images.generate(**request_payload)

        # 解析返回的 URL
        urls = []
        if response.data:
            for img_obj in response.data:
                urls.append(img_obj.url)
                
        return urls

# ==========================================
# 工厂模式：根据名称返回对应的处理类
# ==========================================
def get_ai_provider(provider_name="fal_ai"):
    providers = {
        'fal_ai': FalAIProvider(),
        'volcengine': VolcengineProvider(),  # <--- 注册新的火山引擎提供商
    }
    return providers.get(provider_name, FalAIProvider())