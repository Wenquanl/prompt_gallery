import mimetypes
import os
from datetime import datetime
from pathlib import Path

from django.db.models import F
from django.utils import timezone

from .models import SourceRoot, VisualResource


RESOURCE_TYPE_MAP = {
    'image': {'.jpg', '.jpeg', '.png', '.webp', '.bmp'},
    'gif': {'.gif'},
    'video': {'.mp4', '.mkv', '.avi', '.mov', '.webm'},
    'model': {'.safetensors', '.ckpt', '.pt', '.pth', '.bin', '.gguf', '.onnx', '.blend', '.blender'},
}


def detect_resource_type(file_path):
    suffix = file_path.suffix.lower()
    for resource_type, extensions in RESOURCE_TYPE_MAP.items():
        if suffix in extensions:
            return resource_type
    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type and mime_type.startswith('image/'):
        return 'image'
    if mime_type and mime_type.startswith('video/'):
        return 'video'
    return 'other'


def ensure_source_root(source_path, name=None):
    resolved_path = Path(source_path).expanduser().resolve()
    source_root, _ = SourceRoot.objects.get_or_create(
        root_path=str(resolved_path),
        defaults={'name': name or resolved_path.name},
    )
    if name and source_root.name != name:
        source_root.name = name
        source_root.save(update_fields=['name', 'updated_at'])
    return source_root


def _queue_index(resource_id):
    from .tasks import index_visual_resource_task

    index_visual_resource_task(resource_id)


def mark_source_sync_started(source_root, phase='等待后台任务'):
    started_at = timezone.now()
    SourceRoot.objects.filter(id=source_root.id).update(
        is_syncing=True,
        sync_phase=phase,
        sync_progress_total=0,
        sync_progress_scanned=0,
        index_progress_total=0,
        index_progress_processed=0,
        index_progress_completed=0,
        index_progress_failed=0,
        sync_current_path='',
        sync_started_at=started_at,
        sync_finished_at=None,
        last_sync_error='',
    )
    source_root.is_syncing = True
    source_root.sync_phase = phase
    source_root.sync_progress_total = 0
    source_root.sync_progress_scanned = 0
    source_root.index_progress_total = 0
    source_root.index_progress_processed = 0
    source_root.index_progress_completed = 0
    source_root.index_progress_failed = 0
    source_root.sync_current_path = ''
    source_root.sync_started_at = started_at
    source_root.sync_finished_at = None
    source_root.last_sync_error = ''
    return started_at


def update_source_sync_progress(source_root_id, *, phase=None, scanned=None, total=None, current_path=None):
    update_kwargs = {}
    if phase is not None:
        update_kwargs['sync_phase'] = phase[:64]
    if scanned is not None:
        update_kwargs['sync_progress_scanned'] = max(0, int(scanned))
    if total is not None:
        update_kwargs['sync_progress_total'] = max(0, int(total))
    if current_path is not None:
        update_kwargs['sync_current_path'] = (current_path or '')[:1000]
    if update_kwargs:
        SourceRoot.objects.filter(id=source_root_id).update(**update_kwargs)


def record_source_sync_failure(source_root, error_message):
    finished_at = timezone.now()
    source_root.last_synced_at = finished_at
    source_root.sync_finished_at = finished_at
    source_root.is_syncing = False
    source_root.sync_phase = '扫描失败'
    source_root.last_sync_error = (error_message or '未知同步错误')[:1000]
    source_root.save(
        update_fields=[
            'last_synced_at',
            'last_sync_error',
            'is_syncing',
            'sync_phase',
            'sync_finished_at',
            'updated_at',
        ]
    )


def record_source_index_progress(resource, *, success):
    source_root_id = resource.source_root_id
    if not source_root_id:
        return

    update_kwargs = {
        'sync_phase': '索引处理中',
        'sync_current_path': (resource.relative_path or resource.file_path or '')[:1000],
        'index_progress_processed': F('index_progress_processed') + 1,
        'updated_at': timezone.now(),
    }
    if success:
        update_kwargs['index_progress_completed'] = F('index_progress_completed') + 1
    else:
        update_kwargs['index_progress_failed'] = F('index_progress_failed') + 1

    SourceRoot.objects.filter(
        id=source_root_id,
        is_syncing=True,
        index_progress_total__gt=0,
    ).update(**update_kwargs)

    source_root = SourceRoot.objects.filter(id=source_root_id).only(
        'id',
        'is_syncing',
        'index_progress_total',
        'index_progress_processed',
    ).first()
    if not source_root or not source_root.is_syncing:
        return

    if source_root.index_progress_processed >= source_root.index_progress_total:
        finished_at = timezone.now()
        SourceRoot.objects.filter(id=source_root_id).update(
            is_syncing=False,
            sync_phase='扫描完成',
            sync_finished_at=finished_at,
            sync_current_path='',
            updated_at=finished_at,
        )


def _iter_resource_files(source_path, allowed_types):
    stack = [source_path]
    while stack:
        current_path = stack.pop()
        try:
            with os.scandir(current_path) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                            continue
                        if not entry.is_file(follow_symlinks=False):
                            continue
                    except OSError:
                        continue

                    file_path = Path(entry.path)
                    resource_type = detect_resource_type(file_path)
                    if resource_type not in allowed_types:
                        continue

                    try:
                        stat_result = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue

                    yield file_path, resource_type, stat_result
        except OSError:
            continue


def sync_source_root(source_root, enabled_types=None, skip_missing_check=False, queue_index=True, index_runner=None):
    source_path = Path(source_root.root_path).expanduser().resolve()
    if not source_path.exists() or not source_path.is_dir():
        raise FileNotFoundError(f'资源根目录不存在: {source_path}')

    allowed_types = set(enabled_types or ['image', 'gif', 'video', 'model', 'other'])
    sync_started_at = mark_source_sync_started(source_root, phase='扫描目录中')
    seen_paths = []
    created_count = 0
    updated_count = 0
    queued_count = 0

    index_callback = index_runner or _queue_index
    discovered_files = []
    for discovered_count, (file_path, resource_type, stat_result) in enumerate(_iter_resource_files(source_path, allowed_types), start=1):
        normalized_path = str(file_path)
        relative_path = file_path.relative_to(source_path).as_posix()
        modified_at = timezone.make_aware(
            datetime.fromtimestamp(stat_result.st_mtime),
            timezone.get_current_timezone(),
        )
        discovered_files.append(
            {
                'file_path': normalized_path,
                'relative_path': relative_path,
                'resource_type': resource_type,
                'file_size': stat_result.st_size,
                'modified_at': modified_at,
                'title': file_path.stem,
                'extension': file_path.suffix.lower(),
                'mime_type': mimetypes.guess_type(normalized_path)[0] or 'application/octet-stream',
            }
        )
        if discovered_count == 1 or discovered_count % 200 == 0:
            update_source_sync_progress(
                source_root.id,
                phase='扫描目录中',
                scanned=discovered_count,
                total=discovered_count,
                current_path=relative_path,
            )

    total_count = len(discovered_files)
    update_source_sync_progress(source_root.id, phase='写入索引中', scanned=0, total=total_count, current_path='')

    discovered_paths = [entry['file_path'] for entry in discovered_files]
    existing_resources = {
        resource.file_path: resource
        for resource in VisualResource.objects.filter(file_path__in=discovered_paths).only(
            'id',
            'file_path',
            'relative_path',
            'resource_type',
            'file_size',
            'modified_at',
            'title',
            'extension',
            'mime_type',
            'is_missing',
            'status',
            'source_root_id',
            'last_error',
            'last_synced_at',
            'updated_at',
        )
    }

    resources_to_create = []
    resources_to_update = []
    resources_to_touch = []
    reindex_target_ids = []

    for processed_count, entry in enumerate(discovered_files, start=1):
        normalized_path = entry['file_path']
        seen_paths.append(normalized_path)
        resource = existing_resources.get(normalized_path)
        needs_reindex = resource is None
        if resource is None:
            resources_to_create.append(
                VisualResource(
                    title=entry['title'],
                    file_path=normalized_path,
                    relative_path=entry['relative_path'],
                    source_root=source_root,
                    resource_type=entry['resource_type'],
                    status='pending',
                    extension=entry['extension'],
                    mime_type=entry['mime_type'],
                    file_size=entry['file_size'],
                    modified_at=entry['modified_at'],
                    last_synced_at=sync_started_at,
                )
            )
            created_count += 1
        else:
            changed = False
            if resource.source_root_id != source_root.id:
                resource.source_root = source_root
                changed = True
            if resource.relative_path != entry['relative_path']:
                resource.relative_path = entry['relative_path']
                changed = True
            if resource.resource_type != entry['resource_type']:
                resource.resource_type = entry['resource_type']
                needs_reindex = True
                changed = True
            if resource.file_size != entry['file_size'] or resource.modified_at != entry['modified_at']:
                resource.file_size = entry['file_size']
                resource.modified_at = entry['modified_at']
                resource.status = 'pending'
                resource.is_missing = False
                resource.last_error = ''
                needs_reindex = True
                changed = True
            if resource.title != entry['title']:
                resource.title = entry['title']
                changed = True
            if resource.extension != entry['extension']:
                resource.extension = entry['extension']
                changed = True
            if resource.mime_type != entry['mime_type']:
                resource.mime_type = entry['mime_type']
                changed = True
            if resource.is_missing:
                resource.is_missing = False
                changed = True

            resource.last_synced_at = sync_started_at
            if changed or needs_reindex or resource.status == 'failed':
                resource.updated_at = timezone.now()
                resources_to_update.append(resource)
                updated_count += 1
                if needs_reindex or resource.status == 'failed':
                    reindex_target_ids.append(resource.id)
            else:
                resources_to_touch.append(resource.id)

        if processed_count == total_count or processed_count % 200 == 0:
            update_source_sync_progress(
                source_root.id,
                phase='写入索引中',
                scanned=processed_count,
                total=total_count,
                current_path=entry['relative_path'],
            )

    if resources_to_create:
        created_resources = VisualResource.objects.bulk_create(resources_to_create, batch_size=500)
    else:
        created_resources = []

    if resources_to_update:
        VisualResource.objects.bulk_update(
            resources_to_update,
            [
                'title',
                'relative_path',
                'source_root',
                'resource_type',
                'status',
                'extension',
                'mime_type',
                'file_size',
                'modified_at',
                'last_synced_at',
                'last_error',
                'is_missing',
                'updated_at',
            ],
            batch_size=500,
        )

    if resources_to_touch:
        touch_time = timezone.now()
        for start in range(0, len(resources_to_touch), 500):
            VisualResource.objects.filter(id__in=resources_to_touch[start:start + 500]).update(
                last_synced_at=sync_started_at,
                updated_at=touch_time,
            )

    queue_targets = []
    queue_targets.extend(resource.id for resource in created_resources)
    queue_targets.extend(reindex_target_ids)
    deduped_queue_targets = list(dict.fromkeys(queue_targets))

    if queue_index:
        update_source_sync_progress(source_root.id, phase='派发索引任务中', scanned=total_count, total=total_count, current_path='')
        for resource_id in deduped_queue_targets:
            index_callback(resource_id)
            queued_count += 1

    missing_count = 0
    if not skip_missing_check:
        update_source_sync_progress(source_root.id, phase='标记缺失文件中', scanned=total_count, total=total_count, current_path='')
        missing_qs = source_root.resources.exclude(file_path__in=seen_paths).filter(is_missing=False)
        missing_count = missing_qs.update(
            is_missing=True,
            status='failed',
            last_error='扫描时未找到本地文件',
            last_synced_at=sync_started_at,
            updated_at=timezone.now(),
        )

    finished_at = timezone.now()
    source_root.last_synced_at = finished_at
    source_root.last_sync_created = created_count
    source_root.last_sync_updated = updated_count
    source_root.last_sync_queued = queued_count
    source_root.last_sync_missing = missing_count
    source_root.last_sync_error = ''
    source_root.sync_progress_total = total_count
    source_root.sync_progress_scanned = total_count
    source_root.index_progress_total = queued_count
    source_root.index_progress_processed = 0
    source_root.index_progress_completed = 0
    source_root.index_progress_failed = 0
    source_root.sync_current_path = ''
    source_root.is_syncing = queued_count > 0
    source_root.sync_phase = '等待索引' if queued_count > 0 else '扫描完成'
    source_root.sync_finished_at = None if queued_count > 0 else finished_at
    source_root.save(
        update_fields=[
            'last_synced_at',
            'last_sync_created',
            'last_sync_updated',
            'last_sync_queued',
            'last_sync_missing',
            'last_sync_error',
            'is_syncing',
            'sync_phase',
            'sync_progress_total',
            'sync_progress_scanned',
            'index_progress_total',
            'index_progress_processed',
            'index_progress_completed',
            'index_progress_failed',
            'sync_current_path',
            'sync_finished_at',
            'updated_at',
        ]
    )

    return {
        'created': created_count,
        'updated': updated_count,
        'queued': queued_count,
        'missing': missing_count,
        'source_root_id': source_root.id,
        'source_name': source_root.name,
    }