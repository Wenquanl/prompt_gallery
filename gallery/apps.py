from django.apps import AppConfig
import sys

class GalleryConfig(AppConfig):
    name = 'gallery'

    def ready(self):
        """
        Django 应用启动完成后执行
        在这里预加载 AI 模型，避免用户首次搜索时等待
        """
        # 简单的判断逻辑：防止在执行 makemigrations 或 migrate 时加载沉重的模型
        # 只有在 runserver (开发环境) 或 非 manage.py 启动 (生产环境 WSGI/ASGI) 时才加载
        is_manage_py = any(arg.endswith('manage.py') for arg in sys.argv)
        is_runserver = any(arg == 'runserver' for arg in sys.argv)
        
        if (is_manage_py and is_runserver) or (not is_manage_py):
            try:
                from .ai_utils import load_model_on_startup
                load_model_on_startup()
            except ImportError:
                pass
            except Exception as e:
                print(f"预加载模型时发生错误: {e}")