# visuals/models.py
from django.db import models

class Video(models.Model):
    STATUS_CHOICES = (
        ('pending', '等待处理'),
        ('processing', '抽帧中'),
        ('completed', '处理完成'),
        ('failed', '处理失败'),
    )
    title = models.CharField(max_length=255, verbose_name="视频名称")
    video_path = models.CharField(max_length=1000, unique=True, verbose_name="视频本地路径")
    cover_path = models.CharField(max_length=1000, blank=True, null=True, verbose_name="封面本地路径")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="状态")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="添加时间")

    def __str__(self):
        return self.title