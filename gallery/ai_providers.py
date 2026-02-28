# gallery/ai_providers.py
import os
import base64
import fal_client
from openai import OpenAI
from google import genai
from google.genai import types

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

class GoogleAIProvider(BaseAIProvider):
    def generate(self, model_config, api_args, base_image_files=None):
        # 1. 初始化 Client，使用官方推荐的 client_args 注入底层代理
        proxy_url = "socks5h://127.0.0.1:10808"  # 你的 v2ray 真实代理地址
        
        client = genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options=types.HttpOptions(
                timeout=300.0,
                client_args={
                    "proxy": proxy_url  # 注入同步客户端代理
                },
                async_client_args={
                    "proxy": proxy_url  # 注入异步客户端代理
                }
            )
        )
        model_endpoint = model_config['endpoint']

        # ==========================================
        # 3. 构建多模态输入 (Contents Array)
        # Nano Banana 允许同时传入文本和多达 14 张参考图片
        # ==========================================
        contents = []
        if api_args.get('prompt'):
            contents.append(api_args['prompt'])

        if base_image_files:
            for f in base_image_files:
                img_bytes = f.read()
                mime_type = getattr(f, 'content_type', 'image/jpeg')
                # 将图片直接转为 Google SDK 要求的 Part 对象，免去图床中转
                contents.append(
                    types.Part.from_bytes(data=img_bytes, mime_type=mime_type)
                )

        # ==========================================
        # 4. 构建生图参数与核心配置 (Config)
        # ==========================================
        image_config_kwargs = {
            "aspect_ratio": api_args.get('aspect_ratio', '1:1'),
        }
        # 如果前端传了分辨率参数，则加上 (如 "2K", "4K")
        if 'resolution' in api_args:
            image_config_kwargs["image_size"] = api_args['resolution']
            
        config_kwargs = {
            # 强制只返回图像，避免模型啰嗦返回文本导致解析复杂
            "response_modalities": ["IMAGE"], 
            "image_config": types.ImageConfig(**image_config_kwargs)
        }

        # 💡 特性 A：启用 Google 联网搜索
        if api_args.get('enable_web_search'):
            # 开启网页搜索和图片搜索双重 Grounding
            config_kwargs["tools"] = [
                types.Tool(google_search=types.GoogleSearch(
                    search_types=types.SearchTypes(
                        web_search=types.WebSearch(),
                        image_search=types.ImageSearch()
                    )
                ))
            ]

        # 💡 特性 B：控制思考深度 (目前仅限 Gemini 3.1 Flash 支持)
        if api_args.get('thinking_level'):
            config_kwargs["thinking_config"] = types.ThinkingConfig(
                thinking_level=api_args['thinking_level'],
                include_thoughts=False # 设为 False，避免返回过程中的草图干扰最终结果
            )

        config = types.GenerateContentConfig(**config_kwargs)

        # ==========================================
        # 5. 调用官方多模态生图接口
        # ==========================================
        response = client.models.generate_content(
            model=model_endpoint,
            contents=contents,
            config=config
        )

        # ==========================================
        # 6. 解析结果并转换为 Data URL
        # ==========================================
        urls = []
        if response.parts:
            for part in response.parts:
                # 过滤掉可能的 thought (思考过程输出)
                if getattr(part, 'thought', False):
                    continue
                    
                # 提取最终图像，转换为 Base64 的 Data URL 供前端和下载器使用
                if getattr(part, 'inline_data', None):
                    img_bytes = part.inline_data.data
                    mime = part.inline_data.mime_type or 'image/jpeg'
                    b64_str = base64.b64encode(img_bytes).decode('utf-8')
                    urls.append(f"data:{mime};base64,{b64_str}")
                
        return urls
# ==========================================
# 工厂模式：根据名称返回对应的处理类
# ==========================================
def get_ai_provider(provider_name="fal_ai"):
    providers = {
        'fal_ai': FalAIProvider(),
        'volcengine': VolcengineProvider(),
        'google_ai': GoogleAIProvider(), 
    }
    return providers.get(provider_name, FalAIProvider())