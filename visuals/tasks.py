# gallery/tasks.py
import os
import subprocess
from huey.contrib.djhuey import db_task
from .models import Video

FFMPEG_EXE = r"E:\ffmpeg-8.1-full_build\bin\ffmpeg.exe"
@db_task()
def extract_video_cover_task(video_id, output_dir):
    try:
        # 1. 从数据库捞出这条视频记录
        video = Video.objects.get(id=video_id)
    except Video.DoesNotExist:
        return

    # 2. 更新状态为“处理中”
    video.status = 'processing'
    video.save()

    os.makedirs(output_dir, exist_ok=True)
    basename = os.path.basename(video.video_path)
    filename_without_ext = os.path.splitext(basename)[0]
    output_path = os.path.join(output_dir, f"{filename_without_ext}_cover.jpg")

    command = [
        FFMPEG_EXE,
        '-y',                 
        '-ss', '00:00:01',        # <--- 移到了这里！
        '-i', video.video_path,   
        '-vframes', '1',      
        '-q:v', '2',          
        output_path        
    ]

    try:
        # 优化 2：增加 timeout=60。
        # 如果遇到损坏的超大文件导致 FFmpeg 卡死，60秒后会强行中断，防止 Huey 进程被永久挂起。
        subprocess.run(
            command, 
            check=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            timeout=60  # <--- 新增防卡死机制
        )
        
        video.cover_path = output_path
        video.status = 'completed'
        video.save()
        print(f"✅ 完成: {video.title}")
        
    except subprocess.TimeoutExpired:
        # 捕获超时异常
        video.status = 'failed'
        video.save()
        print(f"❌ 超时失败 (文件可能过大或损坏): {video.title}")
        
    except subprocess.CalledProcessError as e:
        video.status = 'failed'
        video.save()
        print(f"❌ 处理失败: {video.title}")