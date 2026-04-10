# gallery/management/commands/scan_videos.py
import os
from pathlib import Path
from django.core.management.base import BaseCommand
from visuals.models import Video
from visuals.tasks import extract_video_cover_task

class Command(BaseCommand):
    help = '扫描本地视频，入库并丢入 Huey 队列'

    def add_arguments(self, parser):
        parser.add_argument('input_folder', type=str)
        parser.add_argument('output_folder', type=str)

    def handle(self, *args, **kwargs):
        input_folder = kwargs['input_folder']
        output_folder = kwargs['output_folder']
        supported_formats = {'.mp4', '.mkv', '.avi', '.mov'}
        
        path = Path(input_folder)
        if not path.exists() or not path.is_dir():
            self.stdout.write(self.style.ERROR("错误：文件夹不存在"))
            return

        task_count = 0
        skip_count = 0

        for file_path in path.rglob('*'):
            if file_path.suffix.lower() in supported_formats:
                # get_or_create 会自动查重：如果有这个路径的视频就不创建，没有就创建
                video, created = Video.objects.get_or_create(
                    video_path=str(file_path),
                    defaults={'title': file_path.name, 'status': 'pending'}
                )

                # 只有新扫描到的，或者之前处理失败的，才扔进队列重新处理
                if created or video.status == 'failed':
                    extract_video_cover_task(video.id, output_folder)
                    task_count += 1
                else:
                    skip_count += 1 # 已经是 completed 或 processing 的就跳过

        self.stdout.write(self.style.SUCCESS(f"🎉 扫描结束！新增任务: {task_count} 个，跳过已有视频: {skip_count} 个。"))