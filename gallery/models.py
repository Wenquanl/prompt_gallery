import uuid
import os
from django.db import models
from django.utils import timezone
from imagekit.models import ImageSpecField
# 【核心修改】引入 ResizeToFit (按比例缩放)，删掉 ResizeToFill (裁剪)
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

# === 3. 提示词组 ===
class PromptGroup(models.Model):
    title = models.CharField("主题/标题", max_length=200, default="未命名组")
    prompt_text = models.TextField("正向提示词 (Prompt)")
    negative_prompt = models.TextField("负向提示词 (Negative Prompt)", blank=True, null=True)
    model_info = models.CharField("模型信息", max_length=200, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, verbose_name="关联标签")
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    def __str__(self): return self.title
    class Meta:
        verbose_name = "提示词组"
        verbose_name_plural = "提示词组列表"
        ordering = ['-created_at']

# === 4. 生成图 (作品) ===
class ImageItem(models.Model):
    group = models.ForeignKey(PromptGroup, on_delete=models.CASCADE, related_name='images', verbose_name="所属提示词组")
    image = models.ImageField("图片文件", upload_to=unique_file_path)
    
    # 【核心修改】ResizeToFit: 宽度限制600，高度自适应，upscale=False防止小图变糊
    thumbnail = ImageSpecField(source='image',
                               processors=[ResizeToFit(width=600, upscale=False)],
                               format='JPEG',
                               options={'quality': 85})
    
    def __str__(self): return f"生成图 ID: {self.id}"
    class Meta: verbose_name = "生成图"; verbose_name_plural = "生成图集"

# === 5. 参考图 (ReferenceItem) ===
class ReferenceItem(models.Model):
    group = models.ForeignKey(PromptGroup, on_delete=models.CASCADE, related_name='references', verbose_name="所属提示词组")
    image = models.ImageField("参考图文件", upload_to=reference_file_path)
    
    # 【核心修改】参考图也改为自适应
    thumbnail = ImageSpecField(source='image',
                               processors=[ResizeToFit(width=300, upscale=False)],
                               format='JPEG',
                               options={'quality': 85})

    def __str__(self): return f"参考图 ID: {self.id}"
    class Meta: verbose_name = "参考图"; verbose_name_plural = "参考图集"