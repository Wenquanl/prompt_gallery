import os
import shutil
import time
from django.core.management.base import BaseCommand
from django.conf import settings

class Command(BaseCommand):
    help = '清理超过24小时的临时上传文件 (Media/temp_uploads)'

    def handle(self, *args, **options):
        temp_root = os.path.join(settings.MEDIA_ROOT, 'temp_uploads')
        
        if not os.path.exists(temp_root):
            self.stdout.write("临时目录不存在，无需清理。")
            return

        now = time.time()
        # 24小时 = 86400秒
        cutoff = 86400 
        deleted_count = 0

        self.stdout.write(f"正在检查 {temp_root} 下的过期文件...")

        for batch_id in os.listdir(temp_root):
            batch_path = os.path.join(temp_root, batch_id)
            
            if os.path.isdir(batch_path):
                # 获取最后修改时间
                mtime = os.path.getmtime(batch_path)
                if now - mtime > cutoff:
                    try:
                        shutil.rmtree(batch_path)
                        self.stdout.write(self.style.SUCCESS(f'已删除过期批次: {batch_id}'))
                        deleted_count += 1
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f'删除失败 {batch_id}: {e}'))

        self.stdout.write(self.style.SUCCESS(f'清理完成。共删除 {deleted_count} 个过期文件夹。'))