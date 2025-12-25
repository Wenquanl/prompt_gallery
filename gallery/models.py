import uuid
import os
import hashlib
from django.db import models
from django.utils import timezone
from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFit

# === 工具函数 ===
def unique_file_path(instance, filename):
    ext = filename.split('.')[-1]
    filename = f"{uuid.uuid4().hex}.{ext}"
    today = timezone.localtime(timezone.now())
    return f"prompts/{today.year}/{today.month}/{today.day}/{filename}"

def reference_file_path(instance, filename):
    ext = filename.split('.')[-1]
    filename = f"ref_{uuid.uuid4().hex}.{ext}"
    today = timezone.localtime(timezone.now())
    return f"references/{today.year}/{today.month}/{today.day}/{filename}"

# === 1. 标签模型 ===
class Tag(models.Model):
    name = models.CharField("标签名", max_length=30, unique=True)
    def __str__(self): return self.name
    class Meta:
        verbose_name = "标签"
        verbose_name_plural = "标签管理"
        ordering = ['name']

# === 2. AI模型管理 ===
class AIModel(models.Model):
    name = models.CharField("模型名称", max_length=50, unique=True, help_text="例如: Midjourney v6")
    order = models.IntegerField("排序权重", default=0, help_text="数字越大越靠前")
    def __str__(self): return self.name
    class Meta:
        verbose_name = "AI模型"
        verbose_name_plural = "AI模型管理"
        ordering = ['-order', 'name']

# === 3. 提示词组 (卡片) ===
class PromptGroup(models.Model):
    title = models.CharField("主题/标题", max_length=200, default="未命名组")
    prompt_text = models.TextField("正向提示词 (Prompt)")
    # 【新增】第二个正向提示词字段
    prompt_text_zh = models.TextField("中文/辅助提示词", blank=True, null=True)
    
    negative_prompt = models.TextField("负向提示词 (Negative Prompt)", blank=True, null=True)
    model_info = models.CharField("模型信息", max_length=200, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, verbose_name="关联标签")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    
    is_liked = models.BooleanField("是否喜欢", default=False)

    def __str__(self): return self.title
    class Meta:
        verbose_name = "提示词组"
        verbose_name_plural = "提示词组列表"
        ordering = ['-created_at']

# === 4. 生成图 (作品单图) ===
class ImageItem(models.Model):
    group = models.ForeignKey(PromptGroup, on_delete=models.CASCADE, related_name='images', verbose_name="所属提示词组")
    image = models.ImageField("图片文件", upload_to=unique_file_path)
    
    is_liked = models.BooleanField("是否喜欢", default=False)

    # 存储图像特征向量
    feature_vector = models.BinaryField("特征向量", null=True, blank=True)
    
    # 存储图片 MD5 哈希值，用于查重
    image_hash = models.CharField("MD5哈希", max_length=32, blank=True, db_index=True)

    thumbnail = ImageSpecField(source='image',
                               processors=[ResizeToFit(width=600, upscale=False)],
                               format='JPEG',
                               options={'quality': 85})
    
    def save(self, *args, **kwargs):
        # 只有在 image_hash 为空且有图片文件时才计算
        if not self.image_hash and self.image:
            self.calculate_hash()
        super().save(*args, **kwargs)

    def calculate_hash(self):
        md5 = hashlib.md5()
        # 分块读取，防止大文件占满内存
        if self.image:
            # 确保指针在开始位置
            if hasattr(self.image, 'seek'):
                self.image.seek(0)
            for chunk in self.image.chunks():
                md5.update(chunk)
            self.image_hash = md5.hexdigest()
    
    def __str__(self): return f"生成图 ID: {self.id}"
    class Meta: verbose_name = "生成图"; verbose_name_plural = "生成图集"

# === 5. 参考图 (ReferenceItem) ===
class ReferenceItem(models.Model):
    group = models.ForeignKey(PromptGroup, on_delete=models.CASCADE, related_name='references', verbose_name="所属提示词组")
    image = models.ImageField("参考图文件", upload_to=reference_file_path)
    
    thumbnail = ImageSpecField(source='image',
                               processors=[ResizeToFit(width=300, upscale=False)],
                               format='JPEG',
                               options={'quality': 85})

    def __str__(self): return f"参考图 ID: {self.id}"
    class Meta: verbose_name = "参考图"; verbose_name_plural = "参考图集"