import uuid
import os
import hashlib
import difflib
from django.db import models
from django.utils import timezone
from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFit
from rapidfuzz import process, fuzz
import meilisearch
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver


PROVIDER_CHOICES = [
    ('openai', 'OpenAI'),
    ('chatgpt', 'ChatGPT'),
    ('fal_ai', 'Fal.ai'),
    ('volcengine', '火山引擎'),
    ('google_ai', 'Google AI (API)'),
    ('google_flow', 'Google Flow'),
    ('gemini_web', 'Gemini 网页/APP'),  
    ('midjourney', 'Midjourney'),
    ('webui', 'Stable Diffusion WebUI'),
    ('comfyui', 'ComfyUI'),
    ('other', '其他渠道')
]

GPT_IMAGE_CONVERSATION_SOURCE_CHOICES = [
    ('create', 'AI 创作页'),
    ('detail', '作品详情页'),
]

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

# === 新增: 人物标签模型 ===
class Character(models.Model):
    name = models.CharField("人物名称", max_length=50, unique=True, help_text="例如: Tifa, 多人合集")
    order = models.IntegerField("排序权重", default=0, help_text="数字越大越靠前")

    def __str__(self): return self.name
    class Meta:
        verbose_name = "人物标签"
        verbose_name_plural = "人物标签管理"
        ordering = ['-order', 'name']        

# === 3. 提示词组 (卡片) ===
class PromptGroup(models.Model):
    title = models.CharField("主题/标题", max_length=200, default="未命名组")
    prompt_text = models.TextField("正向提示词 (Prompt)")
    prompt_text_zh = models.TextField("中文/辅助提示词", blank=True, null=True)
    
    negative_prompt = models.TextField("负向提示词 (Negative Prompt)", blank=True, null=True)
    prompts = models.JSONField("统一提示词列表", default=list, blank=True)
    searchable_prompts = models.TextField("提示词检索缓存", blank=True, default="")
    model_info = models.CharField("模型信息", max_length=200, blank=True)
    characters = models.ManyToManyField('Character', blank=True, verbose_name="包含人物")
    tags = models.ManyToManyField(Tag, blank=True, verbose_name="关联标签")
    
    created_at = models.DateTimeField("创建时间", auto_now_add=True, db_index=True)
    is_liked = models.BooleanField("是否喜欢", default=False)
    # 【新增】生成渠道字段
    provider = models.CharField(
        "生成渠道", 
        max_length=50, 
        choices=PROVIDER_CHOICES, 
        default='other',
        blank=True
    )
    # 【新增】封面图字段，关联到 ImageItem
    cover_image = models.ForeignKey(
        'ImageItem', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='covered_groups',
        verbose_name="封面图"
    )
    is_main_variant = models.BooleanField("是否为主版本", default=False)
    group_id = models.UUIDField("组ID", default=uuid.uuid4, editable=True, db_index=True)

    def __str__(self): return self.title
    class Meta:
        verbose_name = "提示词组"
        verbose_name_plural = "提示词组列表"
        ordering = ['-created_at']

    @staticmethod
    def normalize_prompts(raw_prompts):
        normalized = []

        if not raw_prompts:
            return normalized

        for index, item in enumerate(raw_prompts, start=1):
            if isinstance(item, dict):
                text = str(item.get('text', '') or '').strip()
            else:
                text = str(item or '').strip()

            if not text:
                continue

            normalized.append({
                'id': f'prompt_{index}',
                'label': f'提示词{len(normalized) + 1}',
                'text': text,
            })

        return normalized

    @classmethod
    def build_prompts_from_legacy_fields(cls, prompt_text='', prompt_text_zh='', negative_prompt=''):
        return cls.normalize_prompts([prompt_text, prompt_text_zh, negative_prompt])

    def get_prompt_items(self):
        prompts = self.normalize_prompts(self.prompts)
        if prompts:
            return prompts
        return self.build_prompts_from_legacy_fields(
            self.prompt_text,
            self.prompt_text_zh,
            self.negative_prompt,
        )

    def get_prompt_texts(self):
        return [item['text'] for item in self.get_prompt_items()]

    def get_primary_prompt_text(self):
        prompt_items = self.get_prompt_items()
        if prompt_items:
            return prompt_items[0]['text']
        return ''

    def get_searchable_prompts_text(self):
        return '\n'.join(self.get_prompt_texts())

    def sync_prompt_storage(self):
        prompt_items = self.normalize_prompts(self.prompts)
        if not prompt_items:
            prompt_items = self.build_prompts_from_legacy_fields(
                self.prompt_text,
                self.prompt_text_zh,
                self.negative_prompt,
            )

        self.prompts = prompt_items
        prompt_texts = [item['text'] for item in prompt_items]
        self.searchable_prompts = '\n'.join(prompt_texts)
        self.prompt_text = prompt_texts[0] if len(prompt_texts) >= 1 else ''
        self.prompt_text_zh = prompt_texts[1] if len(prompt_texts) >= 2 else ''
        self.negative_prompt = prompt_texts[2] if len(prompt_texts) >= 3 else ''

    def save(self, *args, **kwargs):
        self.sync_prompt_storage()
        is_new = self._state.adding
        if is_new:
            self.find_and_join_group()
        super().save(*args, **kwargs)

    def find_and_join_group(self):
        """查找最近的相似提示词组 (C++底层极速批处理版)"""
        my_content = self.get_primary_prompt_text().strip().lower()
        
        if len(my_content) < 5:
            return

        # 1. 内存优化：只取必须的字段，不要拉取整个模型实例
        # 注意要转换成 list 触发 SQL 查询
        candidates = list(PromptGroup.objects.order_by('-id').values_list(
            'group_id', 'title', 'searchable_prompts'
        )[:2000])
        
        # 2. 预过滤并构建待匹配字典 {文本: (group_id, title)}
        valid_candidates = {}
        my_len = len(my_content)
        
        for c_group_id, c_title, c_text in candidates:
            c_text = (c_text or "").strip().lower()
            if not c_text: 
                continue
                
            max_len = max(my_len, len(c_text))
            # 长度相差超过 40% 的直接抛弃，连模糊匹配都不用做
            if abs(my_len - len(c_text)) <= max_len * 0.4:
                valid_candidates[c_text] = (c_group_id, c_title)

        if not valid_candidates:
            print(f"DEBUG: 未找到长度相似的候选项，创建新组。")
            return

        print(f"DEBUG: 正在为 [{self.title}] 查找相似提示词 (底层C++加速)...")
        
        # 3. 核心优化：直接调用 C++ 引擎提取最相似的 1 个
        # score_cutoff=80.0 代表相似度低于 80% 的直接在 C++ 层面短路抛弃，极大提升性能
        best_match = process.extractOne(
            my_content,
            valid_candidates.keys(),
            scorer=fuzz.ratio,
            score_cutoff=80.0
        )
        
        if best_match:
            # extractOne 返回格式: (匹配到的文本, 相似度分数0-100, 索引或Key)
            match_text, score, _ = best_match
            best_group_id, best_match_title = valid_candidates[match_text]
            
            print(f"DEBUG: 匹配成功！关联到 [{best_match_title}]，相似度: {score/100:.2f}")
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
    # 【新增】增加哈希字段，用于去重
    image_hash = models.CharField("MD5哈希", max_length=32, blank=True, db_index=True)
    
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


    # 【新增】哈希计算逻辑
    def calculate_hash(self):
        if not self.image:
            return

        md5 = hashlib.md5()
        if hasattr(self.image, 'seek'):
            self.image.seek(0)
            
        try:
            for chunk in self.image.chunks():
                md5.update(chunk)
        except Exception:
            try:
                content = self.image.read()
                md5.update(content)
            except Exception as e:
                print(f"计算哈希失败: {e}")
                return 

        self.image_hash = md5.hexdigest()
        
        # 将指针归零，并【显式关闭文件】释放 Windows 文件锁
        if hasattr(self.image, 'seek'):
            self.image.seek(0)
        
    def __str__(self): return f"参考图 ID: {self.id}"
    class Meta: verbose_name = "参考图"; verbose_name_plural = "参考图集"


class GPTImageConversation(models.Model):
    conversation_id = models.UUIDField('会话 ID', default=uuid.uuid4, editable=False, unique=True, db_index=True)
    source_page = models.CharField('来源页面', max_length=20, choices=GPT_IMAGE_CONVERSATION_SOURCE_CHOICES)
    source_prompt_group = models.ForeignKey(
        PromptGroup,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='gpt_image_conversations',
        verbose_name='来源作品组',
    )
    source_image = models.ForeignKey(
        ImageItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='source_gpt_image_conversations',
        verbose_name='来源图片',
    )
    active_image = models.ForeignKey(
        ImageItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='active_gpt_image_conversations',
        verbose_name='当前激活图片',
    )
    active_image_path = models.CharField('当前激活图片路径', max_length=500, blank=True)
    model_key = models.CharField('模型 Key', max_length=100)
    model_label = models.CharField('模型名称', max_length=100, blank=True)
    provider = models.CharField('生成渠道', max_length=50, choices=PROVIDER_CHOICES, default='openai', blank=True)
    initial_prompt = models.TextField('初始提示词', blank=True)
    last_instruction = models.TextField('最近一轮调整指令', blank=True)
    latest_params = models.JSONField('最近参数快照', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField('更新时间', auto_now=True)

    class Meta:
        verbose_name = 'GPT 调图会话'
        verbose_name_plural = 'GPT 调图会话'
        ordering = ['-updated_at', '-id']

    def __str__(self):
        return f"GPT 调图会话 {self.conversation_id}"

    def set_active_image_state(self, image_item=None, image_path=''):
        self.active_image = image_item
        self.active_image_path = image_path or getattr(getattr(image_item, 'image', None), 'name', '') or ''


class GPTImageConversationTurn(models.Model):
    conversation = models.ForeignKey(
        GPTImageConversation,
        on_delete=models.CASCADE,
        related_name='turns',
        verbose_name='所属会话',
    )
    turn_index = models.PositiveIntegerField('轮次序号')
    instruction = models.TextField('调整指令')
    input_image = models.ForeignKey(
        ImageItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='input_gpt_image_conversation_turns',
        verbose_name='输入图片',
    )
    input_image_path = models.CharField('输入图片路径', max_length=500, blank=True)
    mask_image_path = models.CharField('蒙版路径', max_length=500, blank=True)
    output_image = models.ForeignKey(
        ImageItem,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='output_gpt_image_conversation_turns',
        verbose_name='输出图片',
    )
    output_image_path = models.CharField('输出图片路径', max_length=500, blank=True)
    request_payload = models.JSONField('请求快照', default=dict, blank=True)
    response_payload = models.JSONField('响应快照', default=dict, blank=True)
    created_at = models.DateTimeField('创建时间', auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = 'GPT 调图轮次'
        verbose_name_plural = 'GPT 调图轮次'
        ordering = ['turn_index', 'id']
        constraints = [
            models.UniqueConstraint(fields=['conversation', 'turn_index'], name='unique_gpt_conversation_turn_index'),
        ]

    def __str__(self):
        return f"{self.conversation_id} - 第 {self.turn_index} 轮"

# ==========================================
# Meilisearch 搜索引擎自动同步机制
# ==========================================
import meilisearch
from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver

# 建立客户端连接（记得填入你的 Master Key）
MEILI_CLIENT = meilisearch.Client('http://127.0.0.1:7700', 'dq49aaqs-RYHbIfKGMOFJRrfco3jP-0Ubj4gcX9caBc')

def sync_promptgroup_to_meili(instance):
    """将 PromptGroup 的核心文本数据组装并推送给搜索引擎"""
    try:
        tags_list = [t.name for t in instance.tags.all()] if instance.pk else []
        chars_list = []
        if instance.pk and hasattr(instance, 'characters'):
            chars_list = [c.name for c in instance.characters.all()]
        prompt_items = instance.get_prompt_items()

        document = {
            'id': instance.id,
            'title': instance.title,
            'prompt_text': instance.prompt_text or '',
            'prompt_text_zh': instance.prompt_text_zh or '',
            'negative_prompt': instance.negative_prompt or '',
            'prompts': [item['text'] for item in prompt_items],
            'searchable_prompts': instance.searchable_prompts or '',
            'model_info': instance.model_info or '',
            'tags': tags_list,
            'characters': chars_list,
        }
        MEILI_CLIENT.index('prompts').add_documents([document])
    except Exception as e:
        print(f"⚠️ Meilisearch 同步失败 (检查服务是否启动或 Key 是否正确): {e}")

# 1. 监听模型保存 (新建/修改)
@receiver(post_save, sender=PromptGroup)
def on_promptgroup_save(sender, instance, **kwargs):
    sync_promptgroup_to_meili(instance)

# 2. 监听多对多字段变化 (标签或人物的增删)
@receiver(m2m_changed, sender=PromptGroup.tags.through)
@receiver(m2m_changed, sender=PromptGroup.characters.through)
def on_promptgroup_m2m_change(sender, instance, action, **kwargs):
    if action in ['post_add', 'post_remove', 'post_clear']:
        sync_promptgroup_to_meili(instance)

# 3. 监听模型删除
@receiver(post_delete, sender=PromptGroup)
def on_promptgroup_delete(sender, instance, **kwargs):
    try:
        MEILI_CLIENT.index('prompts').delete_document(instance.id)
    except:
        pass