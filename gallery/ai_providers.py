# gallery/ai_providers.py
import os
import fal_client

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


# ==========================================
# 工厂模式：根据名称返回对应的处理类
# ==========================================
def get_ai_provider(provider_name="fal_ai"):
    providers = {
        'fal_ai': FalAIProvider(),
        # 未来如果要加官方接口，只需在这里注册，例如：
        # 'aliyun_dashscope': DashScopeProvider(),
        # 'bytedance_volc': VolcengineProvider(),
    }
    return providers.get(provider_name, FalAIProvider())