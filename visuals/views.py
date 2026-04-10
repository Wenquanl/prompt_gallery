import os
from django.shortcuts import render, get_object_or_404 # 引入 get_object_or_404
from django.http import FileResponse, Http404        # 引入 FileResponse 和 Http404
from django.conf import settings
from .models import Video

def visuals_view(request):
    videos = Video.objects.filter(status='completed').order_by('-created_at')
    for video in videos:
        if video.cover_path:
            try:
                rel_path = os.path.relpath(video.cover_path, settings.MEDIA_ROOT)
                rel_path = rel_path.replace('\\', '/')
                video.cover_url = f"{settings.MEDIA_URL}{rel_path}"
            except ValueError:
                video.cover_url = ""
        else:
            video.cover_url = ""
            
    # 注意这里模板路径改成了 visuals/index.html
    return render(request, 'visuals/index.html', {'videos': videos})

def stream_video(request, video_id):
    """
    流媒体播放接口：根据 ID 找到视频物理路径，并以视频流格式返回给前端
    """
    video = get_object_or_404(Video, id=video_id)
    
    if os.path.exists(video.video_path):
        # Django 的 FileResponse 会自动处理视频的 Range 请求（也就是支持快进/后退进度条）
        # 'rb' 表示以二进制只读模式打开文件
        return FileResponse(open(video.video_path, 'rb'), content_type='video/mp4')
    else:
        raise Http404("视频文件在本地硬盘上找不到了！")