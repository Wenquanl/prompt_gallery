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
    """生成唯一的图片/视频存储路径"""
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
    # 【新增】封面图字段，关联到 ImageItem
    cover_image = models.ForeignKey(
        'ImageItem', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='covered_groups',
        verbose_name="封面图"
    )
    group_id = models.UUIDField("组ID", default=uuid.uuid4, editable=True, db_index=True)

    def __str__(self): return self.title
    class Meta:
        verbose_name = "提示词组"
        verbose_name_plural = "提示词组列表"
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if is_new:
            self.find_and_join_group()
        super().save(*args, **kwargs)

    def find_and_join_group(self):
        """查找最近的相似提示词组 (仅比较正向提示词)"""
        my_content = (self.prompt_text or "").strip().lower()
        
        if len(my_content) < 5:
            return

        # [修复1] 扩大搜索范围，防止只能匹配最近500条，建议改为2000或更多
        candidates = PromptGroup.objects.order_by('-id')[:2000]
        
        best_ratio = 0
        best_group_id = None
        best_match_title = None
        
        print(f"DEBUG: 正在为 [{self.title}] 查找相似提示词...")
        for other in candidates:
            other_content = (other.prompt_text or "").strip().lower()
            
            # [修复2] 长度过滤逻辑不对称修复
            # 改为：如果长度差 > 最长文本的40%，则跳过。确保 A和B 比较结果一致。
            max_len = max(len(my_content), len(other_content))
            if max_len == 0: continue
            
            if abs(len(my_content) - len(other_content)) > max_len * 0.4:
                continue

            ratio = difflib.SequenceMatcher(None, my_content, other_content).ratio()
            if ratio > 0.80 and ratio > best_ratio:
                best_ratio = ratio
                best_group_id = other.group_id
                best_match_title = other.title # 记录一下匹配到的标题用于日志
        
        if best_group_id:
            print(f"DEBUG: 匹配成功！关联到 [{best_match_title}]，相似度: {best_ratio:.2f}")
            self.group_id = best_group_id
        else:
            print(f"DEBUG: 未找到相似度 > 0.8 的组，创建新组。")

# === 4. 生成图 (作品单图/视频) ===
class ImageItem(models.Model):
    group = models.ForeignKey(PromptGroup, on_delete=models.CASCADE, related_name='images', verbose_name="所属提示词组")
    image = models.FileField("文件", upload_to=unique_file_path)
    
    is_liked = models.BooleanField("是否喜欢", default=False)
    feature_vector = models.BinaryField("特征向量", null=True, blank=True)
    image_hash = models.CharField("MD5哈希", max_length=32, blank=True, db_index=True)

    thumbnail = ImageSpecField(source='image',
                               processors=[ResizeToFit(width=600, upscale=False)],
                               format='JPEG',
                               options={'quality': 85})
    
    @property
    def is_video(self):
        """判断是否为视频文件"""
        if not self.image or not self.image.name:
            return False
        # 确保已导入 os
        ext = os.path.splitext(self.image.name)[1].lower()
        return ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']

    def save(self, *args, **kwargs):
        if not self.image_hash and self.image:
            self.calculate_hash()
        super().save(*args, **kwargs)

    def calculate_hash(self):
        md5 = hashlib.md5()
        if self.image:
            if hasattr(self.image, 'seek'):
                self.image.seek(0)
            for chunk in self.image.chunks():
                md5.update(chunk)
            self.image_hash = md5.hexdigest()
            if hasattr(self.image, 'seek'):
                self.image.seek(0)
    
    def __str__(self): return f"生成文件 ID: {self.id}"
    class Meta: verbose_name = "生成图"; verbose_name_plural = "生成图集"

# === 5. 参考图 (ReferenceItem) ===
class ReferenceItem(models.Model):
    group = models.ForeignKey(PromptGroup, on_delete=models.CASCADE, related_name='references', verbose_name="所属提示词组")
    image = models.FileField("参考文件", upload_to=reference_file_path)
    
    thumbnail = ImageSpecField(source='image',
                               processors=[ResizeToFit(width=300, upscale=False)],
                               format='JPEG',
                               options={'quality': 85})

    @property
    def is_video(self):
        if not self.image or not self.image.name:
            return False
        ext = os.path.splitext(self.image.name)[1].lower()
        return ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']

    def __str__(self): return f"参考图 ID: {self.id}"
    class Meta: verbose_name = "参考图"; verbose_name_plural = "参考图集"