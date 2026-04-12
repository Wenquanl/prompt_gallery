# visuals/models.py
import mimetypes
import os
from django.db import models


class SourceRoot(models.Model):
    name = models.CharField(max_length=120, unique=True, verbose_name="资源源名称")
    root_path = models.CharField(max_length=1000, unique=True, verbose_name="根目录路径")
    is_enabled = models.BooleanField(default=True, verbose_name="启用扫描")
    is_syncing = models.BooleanField(default=False, verbose_name="扫描中")
    metadata_task_state = models.CharField(max_length=16, blank=True, verbose_name="整源设置任务状态")
    metadata_task_action = models.CharField(max_length=32, blank=True, verbose_name="整源设置任务动作")
    metadata_task_target = models.CharField(max_length=120, blank=True, verbose_name="整源设置任务目标")
    metadata_task_total = models.PositiveIntegerField(default=0, verbose_name="整源设置任务数量")
    metadata_task_started_at = models.DateTimeField(null=True, blank=True, verbose_name="整源设置任务开始时间")
    metadata_task_finished_at = models.DateTimeField(null=True, blank=True, verbose_name="整源设置任务结束时间")
    metadata_task_message = models.CharField(max_length=255, blank=True, verbose_name="整源设置任务提示")
    sync_phase = models.CharField(max_length=64, blank=True, verbose_name="扫描阶段")
    sync_progress_total = models.PositiveIntegerField(default=0, verbose_name="扫描总数")
    sync_progress_scanned = models.PositiveIntegerField(default=0, verbose_name="已扫描数量")
    index_progress_total = models.PositiveIntegerField(default=0, verbose_name="索引总数")
    index_progress_processed = models.PositiveIntegerField(default=0, verbose_name="已处理索引数")
    index_progress_completed = models.PositiveIntegerField(default=0, verbose_name="索引成功数")
    index_progress_failed = models.PositiveIntegerField(default=0, verbose_name="索引失败数")
    sync_current_path = models.CharField(max_length=1000, blank=True, verbose_name="当前扫描路径")
    sync_started_at = models.DateTimeField(null=True, blank=True, verbose_name="扫描开始时间")
    sync_finished_at = models.DateTimeField(null=True, blank=True, verbose_name="扫描结束时间")
    last_synced_at = models.DateTimeField(null=True, blank=True, verbose_name="最近同步时间")
    last_sync_created = models.PositiveIntegerField(default=0, verbose_name="上次同步新增")
    last_sync_updated = models.PositiveIntegerField(default=0, verbose_name="上次同步更新")
    last_sync_queued = models.PositiveIntegerField(default=0, verbose_name="上次同步索引任务")
    last_sync_missing = models.PositiveIntegerField(default=0, verbose_name="上次同步缺失")
    last_sync_error = models.TextField(blank=True, verbose_name="上次同步错误")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "资源源"
        verbose_name_plural = "资源源"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Collection(models.Model):
    name = models.CharField(max_length=80, unique=True, verbose_name="合集名称")
    description = models.TextField(blank=True, verbose_name="合集描述")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "资源合集"
        verbose_name_plural = "资源合集"
        ordering = ["name"]

    def __str__(self):
        return self.name


class VisualResource(models.Model):
    STATUS_CHOICES = (
        ("pending", "等待索引"),
        ("processing", "处理中"),
        ("completed", "已完成"),
        ("failed", "处理失败"),
    )
    RESOURCE_TYPE_CHOICES = (
        ("image", "图片"),
        ("video", "视频"),
        ("gif", "GIF"),
        ("model", "模型文件"),
        ("other", "其他文件"),
    )

    title = models.CharField(max_length=255, verbose_name="资源名称")
    file_path = models.CharField(max_length=1000, unique=True, verbose_name="本地路径")
    relative_path = models.CharField(max_length=1000, blank=True, verbose_name="相对路径")
    cover_path = models.CharField(max_length=1000, blank=True, null=True, verbose_name="封面路径")
    source_root = models.ForeignKey(
        SourceRoot,
        on_delete=models.SET_NULL,
        related_name="resources",
        null=True,
        blank=True,
        verbose_name="所属资源源",
    )
    resource_type = models.CharField(
        max_length=20,
        choices=RESOURCE_TYPE_CHOICES,
        default="video",
        db_index=True,
        verbose_name="资源类型",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="pending",
        db_index=True,
        verbose_name="状态",
    )
    extension = models.CharField(max_length=20, blank=True, verbose_name="扩展名")
    mime_type = models.CharField(max_length=120, blank=True, verbose_name="MIME 类型")
    file_hash = models.CharField(max_length=32, blank=True, db_index=True, verbose_name="文件哈希")
    file_size = models.BigIntegerField(null=True, blank=True, verbose_name="文件大小")
    width = models.PositiveIntegerField(null=True, blank=True, verbose_name="宽度")
    height = models.PositiveIntegerField(null=True, blank=True, verbose_name="高度")
    duration_seconds = models.FloatField(null=True, blank=True, verbose_name="时长(秒)")
    modified_at = models.DateTimeField(null=True, blank=True, verbose_name="文件修改时间")
    indexed_at = models.DateTimeField(null=True, blank=True, verbose_name="最近索引时间")
    last_synced_at = models.DateTimeField(null=True, blank=True, verbose_name="最近同步时间")
    last_error = models.TextField(blank=True, verbose_name="最近错误")
    is_liked = models.BooleanField(default=False, verbose_name="已收藏")
    is_missing = models.BooleanField(default=False, db_index=True, verbose_name="文件已丢失")
    tags = models.ManyToManyField("gallery.Tag", blank=True, related_name="visual_resources", verbose_name="标签")
    collections = models.ManyToManyField(Collection, blank=True, related_name="resources", verbose_name="合集")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, verbose_name="添加时间")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="更新时间")

    class Meta:
        verbose_name = "本地资源"
        verbose_name_plural = "本地资源"
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.title or self.file_name

    @property
    def file_name(self):
        return os.path.basename(self.file_path)

    @property
    def directory_name(self):
        return os.path.dirname(self.relative_path or self.file_path)

    @property
    def is_streamable(self):
        return self.resource_type == "video"

    @property
    def has_preview(self):
        if self.resource_type in {"image", "gif"}:
            return True
        return bool(self.cover_path)

    def refresh_basic_metadata(self):
        self.extension = os.path.splitext(self.file_path)[1].lower()
        guessed_mime, _ = mimetypes.guess_type(self.file_path)
        self.mime_type = guessed_mime or "application/octet-stream"


Video = VisualResource


# ==========================================
# Meilisearch 自动同步
# ==========================================
try:
    import meilisearch as _meilisearch
    from django.conf import settings as _djsettings
    _VISUALS_MEILI_CLIENT = _meilisearch.Client(
        getattr(_djsettings, 'MEILI_URL', 'http://127.0.0.1:7700'),
        getattr(_djsettings, 'MEILI_KEY', 'dq49aaqs-RYHbIfKGMOFJRrfco3jP-0Ubj4gcX9caBc'),
    )
except Exception:
    _VISUALS_MEILI_CLIENT = None

VISUALS_MEILI_INDEX = 'visuals_resources'


def _build_visual_meili_doc(instance):
    return {
        'id': instance.id,
        'title': instance.title,
        'file_path': instance.file_path,
        'relative_path': instance.relative_path,
        'resource_type': instance.resource_type,
        'extension': instance.extension,
        'tags': [t.name for t in instance.tags.all()],
        'collections': [c.name for c in instance.collections.all()],
        'is_liked': instance.is_liked,
        'is_missing': instance.is_missing,
        'status': instance.status,
        'source_name': instance.source_root.name if instance.source_root else '',
    }


def _sync_visual_to_meili(instance):
    if _VISUALS_MEILI_CLIENT is None or not instance.pk:
        return
    try:
        _VISUALS_MEILI_CLIENT.index(VISUALS_MEILI_INDEX).add_documents([_build_visual_meili_doc(instance)])
    except Exception as exc:
        print(f"Visuals Meilisearch sync failed: {exc}")


def _sync_visuals_to_meili(instances, batch_size=200):
    if _VISUALS_MEILI_CLIENT is None:
        return

    docs = []
    try:
        for instance in instances:
            if not instance.pk:
                continue
            docs.append(_build_visual_meili_doc(instance))
            if len(docs) >= batch_size:
                _VISUALS_MEILI_CLIENT.index(VISUALS_MEILI_INDEX).add_documents(docs)
                docs = []
        if docs:
            _VISUALS_MEILI_CLIENT.index(VISUALS_MEILI_INDEX).add_documents(docs)
    except Exception as exc:
        print(f"Visuals Meilisearch sync failed: {exc}")


from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver


@receiver(post_save, sender=VisualResource)
def _on_visual_resource_save(sender, instance, **kwargs):
    _sync_visual_to_meili(instance)


@receiver(m2m_changed, sender=VisualResource.tags.through)
@receiver(m2m_changed, sender=VisualResource.collections.through)
def _on_visual_resource_m2m(sender, instance, action, **kwargs):
    if action in ('post_add', 'post_remove', 'post_clear') and isinstance(instance, VisualResource):
        _sync_visual_to_meili(instance)


@receiver(post_delete, sender=VisualResource)
def _on_visual_resource_delete(sender, instance, **kwargs):
    if _VISUALS_MEILI_CLIENT is None:
        return
    try:
        _VISUALS_MEILI_CLIENT.index(VISUALS_MEILI_INDEX).delete_document(instance.id)
    except Exception:
        pass