import uuid
import os
import hashlib
import difflib
from django.db import models
from django.utils import timezone
from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFit

# === 工具函数 ===
def unique_file_path(instance, filename):
    """生成唯一的图片存储路径 (yyyy/mm/dd/uuid.ext)"""
    ext = filename.split('.')[-1]
    filename = f"{uuid.uuid4().hex}.{ext}"
    today = timezone.localtime(timezone.now())
    return f"prompts/{today.year}/{today.month}/{today.day}/{filename}"

def reference_file_path(instance, filename):
    """生成参考图存储路径"""
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
    prompt_text_zh = models.TextField("中文/辅助提示词", blank=True, null=True)
    
    negative_prompt = models.TextField("负向提示词 (Negative Prompt)", blank=True, null=True)
    model_info = models.CharField("模型信息", max_length=200, blank=True)
    tags = models.ManyToManyField(Tag, blank=True, verbose_name="关联标签")
    
    created_at = models.DateTimeField("创建时间", auto_now_add=True, db_index=True)
    is_liked = models.BooleanField("是否喜欢", default=False)

    # 【新增】家族ID：同一系列的变体共享同一个ID
    group_id = models.UUIDField("组ID", default=uuid.uuid4, editable=True, db_index=True)

    def __str__(self): return self.title
    class Meta:
        verbose_name = "提示词组"
        verbose_name_plural = "提示词组列表"
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        
        # 如果是新创建的，尝试自动寻找家族
        if is_new:
            self.find_and_join_group()

        super().save(*args, **kwargs)

    def find_and_join_group(self):
        """查找最近的相似提示词组 (仅比较正向提示词)"""
        # 【修正】只比较正向提示词，去掉首尾空格并转小写
        my_content = (self.prompt_text or "").strip().lower()
        
        # 如果提示词太短（比如少于5个字符），就不自动归类了，避免误判
        if len(my_content) < 5:
            return

        # 性能优化：只跟最近的 50 条比较 (变体通常是连续生成的)
        candidates = PromptGroup.objects.order_by('-id')[:50]
        
        best_ratio = 0
        best_group_id = None

        for other in candidates:
            # 【修正】同样只取正向提示词
            other_content = (other.prompt_text or "").strip().lower()
            
            # 简单的长度预筛选
            if abs(len(my_content) - len(other_content)) > len(my_content) * 0.4:
                continue

            # 计算相似度
            ratio = difflib.SequenceMatcher(None, my_content, other_content).ratio()
            
            # 阈值：0.85 (85% 相似)
            if ratio > 0.85 and ratio > best_ratio:
                best_ratio = ratio
                best_group_id = other.group_id
        
        if best_group_id:
            self.group_id = best_group_id
        """查找最近的相似提示词组，如果相似度 > 85% 则加入其 group_id"""
        my_content = (self.prompt_text or "").strip() + " " + (self.negative_prompt or "").strip()
        
        # 性能优化：只跟最近的 200 条比较
        candidates = PromptGroup.objects.order_by('-id')[:200]
        
        best_ratio = 0
        best_group_id = None

        for other in candidates:
            other_content = (other.prompt_text or "").strip() + " " + (other.negative_prompt or "").strip()
            
            # 简单的长度预筛选
            if abs(len(my_content) - len(other_content)) > len(my_content) * 0.3:
                continue

            # 计算相似度
            ratio = difflib.SequenceMatcher(None, my_content, other_content).ratio()
            
            # 阈值设定为 0.85 (85% 相似)
            if ratio > 0.85 and ratio > best_ratio:
                best_ratio = ratio
                best_group_id = other.group_id
        
        # 如果找到了相似的组，就加入它；否则保持默认生成的新的 UUID
        if best_group_id:
            self.group_id = best_group_id

# === 4. 生成图 (作品单图) ===
class ImageItem(models.Model):
    group = models.ForeignKey(PromptGroup, on_delete=models.CASCADE, related_name='images', verbose_name="所属提示词组")
    image = models.ImageField("图片文件", upload_to=unique_file_path)
    
    is_liked = models.BooleanField("是否喜欢", default=False)

    # 存储图像特征向量 (用于以图搜图)
    feature_vector = models.BinaryField("特征向量", null=True, blank=True)
    
    # 存储图片 MD5 哈希值，用于查重，已加索引
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
        """
        计算文件哈希，并确保文件指针复位，防止影响后续的图片保存操作
        """
        md5 = hashlib.md5()
        if self.image:
            # 1. 确保指针在开始位置
            if hasattr(self.image, 'seek'):
                self.image.seek(0)
            
            # 2. 读取内容计算哈希
            for chunk in self.image.chunks():
                md5.update(chunk)
            
            self.image_hash = md5.hexdigest()

            # 3. 【关键】计算完成后，必须重置指针回 0
            # 否则后续的 save() 方法读取到的将是空内容
            if hasattr(self.image, 'seek'):
                self.image.seek(0)
    
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