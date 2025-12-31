import os
import sys
import threading
import time
from django.apps import AppConfig
from django.core.management import call_command

def run_cleanup_loop():
    """后台循环：每小时检查并清理一次过期临时文件"""
    while True:
        # 启动后先等待 10 分钟再首次运行，避免影响服务器启动速度
        time.sleep(600) 
        try:
            print(">> [后台任务] 开始清理过期临时文件...")
            # 调用你写好的 cleanup_temp 命令
            call_command('cleanup_temp')
        except Exception as e:
            print(f">> [后台任务] 清理出错: {e}")
        
        # 之后每 1 小时运行一次 (3600秒)
        time.sleep(3600)

class GalleryConfig(AppConfig):
    name = 'gallery'

    def ready(self):
        """
        Django 应用启动完成后执行
        """
        # 判断是否处于 Server 运行模式（避免在 migrate 等命令时执行）
        is_manage_py = any(arg.endswith('manage.py') for arg in sys.argv)
        is_runserver = any(arg == 'runserver' for arg in sys.argv)
        
        should_run_tasks = (is_manage_py and is_runserver) or (not is_manage_py)

        if should_run_tasks:
            # 1. 预加载 AI 模型 (保留原有逻辑)
            try:
                from .ai_utils import load_model_on_startup
                load_model_on_startup()
            except ImportError:
                pass
            except Exception as e:
                print(f"预加载模型时发生错误: {e}")

            # 2. 启动后台清理线程
            # 只有在 runserver 的主进程 (RUN_MAIN='true') 或非 runserver 环境下启动
            # 避免开发环境下自动重载导致开启两个线程
            if os.environ.get('RUN_MAIN') == 'true' or not is_runserver:
                cleanup_thread = threading.Thread(target=run_cleanup_loop, daemon=True)
                cleanup_thread.start()
                print(">> 自动清理服务已启动 (后台线程)")