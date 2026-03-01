import os
import shutil
import tarfile
from datetime import datetime
from django.core.management.base import BaseCommand
from django.core.management import call_command
from django.conf import settings

class Command(BaseCommand):
    help = '备份数据库、图片和视频数据'

    def handle(self, *args, **options):
        # 1. 设置备份目录
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_root = os.path.join(settings.BASE_DIR, 'backups')
        current_backup_dir = os.path.join(backup_root, f'backup_{timestamp}')
        
        if not os.path.exists(current_backup_dir):
            os.makedirs(current_backup_dir)

        self.stdout.write(f'开始备份至: {current_backup_dir}...')

        try:
            # 2. 备份数据库 (导出为 JSON)
            db_file = os.path.join(current_backup_dir, 'database_dump.json')
            with open(db_file, 'w', encoding='utf-8') as f:
                call_command('dumpdata', indent=4, stdout=f)
            self.stdout.write(self.style.SUCCESS('数据库记录已备份。'))

            # 3. 备份媒体文件 (图片与视频)
            # 在你的模型中，文件路径由 unique_file_path 和 reference_file_path 生成
            media_root = settings.MEDIA_ROOT
            if os.path.exists(media_root):
                media_backup_file = os.path.join(current_backup_dir, 'media_files.tar.gz')
                with tarfile.open(media_backup_file, "w:gz") as tar:
                    tar.add(media_root, arcname=os.path.basename(media_root))
                self.stdout.write(self.style.SUCCESS(f'媒体文件（含图片/视频）已备份至压缩包。'))
            else:
                self.stdout.write(self.style.WARNING('未找到 MEDIA_ROOT 目录，跳过媒体备份。'))

            # 4. 打包最终备份文件夹
            final_archive = f"{current_backup_dir}.zip"
            shutil.make_archive(current_backup_dir, 'zip', current_backup_dir)
            
            # 清理临时文件夹，只保留压缩包
            shutil.rmtree(current_backup_dir)
            
            self.stdout.write(self.style.SUCCESS(f'🎉 备份完成！最终文件: {final_archive}'))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f'备份失败: {str(e)}'))