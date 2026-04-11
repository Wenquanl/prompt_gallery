import json
import hashlib
import os
import mimetypes
import subprocess
import threading
import warnings
from contextlib import contextmanager
from datetime import datetime

from django.conf import settings
from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_task, periodic_task

from .models import SourceRoot, VisualResource
from .sync import mark_source_sync_started, record_source_index_progress, record_source_sync_failure, sync_source_root


try:
    from PIL import Image
except ImportError:
    Image = None


_PIL_IMAGE_OPEN_LOCK = threading.Lock()


def _get_preview_root():
    return getattr(settings, 'VISUALS_PREVIEW_ROOT', os.path.join(settings.MEDIA_ROOT, 'visuals_previews'))


def _get_ffmpeg_executable():
    return getattr(settings, 'VISUALS_FFMPEG_EXE', 'ffmpeg')


def _get_ffprobe_executable():
    return getattr(settings, 'VISUALS_FFPROBE_EXE', 'ffprobe')


@contextmanager
def _open_pillow_image(path):
    if Image is None:
        raise RuntimeError('Pillow 不可用')
    decompression_warning = getattr(Image, 'DecompressionBombWarning', Warning)
    with _PIL_IMAGE_OPEN_LOCK:
        original_max_pixels = getattr(Image, 'MAX_IMAGE_PIXELS', None)
        try:
            Image.MAX_IMAGE_PIXELS = None
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', decompression_warning)
                with Image.open(path) as image:
                    yield image
        finally:
            Image.MAX_IMAGE_PIXELS = original_max_pixels


def _format_subprocess_error(error_output):
    text = error_output.decode('utf-8', errors='ignore') if isinstance(error_output, bytes) else str(error_output or '')
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return '外部工具执行失败'
    filtered_lines = [line for line in lines if not line.lower().startswith('ffmpeg version') and not line.lower().startswith('built with') and not line.lower().startswith('configuration:')]
    useful_lines = filtered_lines or lines
    return '\n'.join(useful_lines[-6:])[:1000]


def _get_video_cover_seek_seconds(resource):
    duration = resource.duration_seconds or 0
    if duration <= 0:
        return 0
    if duration <= 1:
        return max(0, round(duration / 2, 3))
    return min(1.0, max(0.1, round(duration * 0.25, 3)))


def _get_sync_schedule():
    sync_minutes = max(1, int(getattr(settings, 'VISUALS_SYNC_MINUTES', 5)))
    if sync_minutes >= 60:
        return crontab(minute='0')
    return crontab(minute=f'*/{sync_minutes}')


def _set_file_timestamps(resource):
    stat_result = os.stat(resource.file_path)
    resource.file_size = stat_result.st_size
    resource.modified_at = timezone.make_aware(datetime.fromtimestamp(stat_result.st_mtime), timezone.get_current_timezone())


def _calculate_file_hash(path):
    md5 = hashlib.md5()
    with open(path, 'rb') as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b''):
            md5.update(chunk)
    return md5.hexdigest()


def _populate_image_metadata(resource):
    if Image is None:
        return
    with _open_pillow_image(resource.file_path) as image:
        resource.width, resource.height = image.size


def _populate_video_metadata(resource):
    command = [
        _get_ffprobe_executable(),
        '-hide_banner',
        '-loglevel', 'error',
        '-show_entries', 'stream=width,height:format=duration',
        '-of', 'json',
        resource.file_path,
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=30)
    payload = json.loads(result.stdout or '{}')
    streams = payload.get('streams') or []
    first_stream = streams[0] if streams else {}
    format_data = payload.get('format') or {}
    if first_stream.get('width'):
        resource.width = int(first_stream['width'])
    if first_stream.get('height'):
        resource.height = int(first_stream['height'])
    if format_data.get('duration'):
        resource.duration_seconds = round(float(format_data['duration']), 2)


def _generate_video_cover(resource, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    filename_without_ext = os.path.splitext(resource.file_name)[0]
    output_path = os.path.join(output_dir, f'{filename_without_ext}_cover.jpg')
    seek_seconds = _get_video_cover_seek_seconds(resource)
    command = [
        _get_ffmpeg_executable(),
        '-hide_banner',
        '-loglevel', 'error',
        '-y',
        '-ss', str(seek_seconds),
        '-i', resource.file_path,
        '-vframes', '1',
        '-q:v', '2',
        output_path,
    ]
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    resource.cover_path = output_path


def run_index_visual_resource(resource_id, output_dir=None):
    try:
        resource = VisualResource.objects.get(id=resource_id)
    except VisualResource.DoesNotExist:
        return

    if not os.path.exists(resource.file_path):
        resource.is_missing = True
        resource.status = 'failed'
        resource.last_error = '本地文件不存在'
        resource.save(update_fields=['is_missing', 'status', 'last_error', 'updated_at'])
        record_source_index_progress(resource, success=False)
        return

    resource.is_missing = False
    resource.status = 'processing'
    resource.last_error = ''
    resource.refresh_basic_metadata()
    resource.save(update_fields=['is_missing', 'status', 'last_error', 'extension', 'mime_type', 'updated_at'])

    try:
        _set_file_timestamps(resource)
        resource.file_hash = _calculate_file_hash(resource.file_path)
        resource.cover_path = resource.cover_path or ''
        if resource.resource_type in {'image', 'gif'}:
            _populate_image_metadata(resource)
            if resource.resource_type == 'gif':
                resource.duration_seconds = resource.duration_seconds or 0
        elif resource.resource_type == 'video':
            _populate_video_metadata(resource)
            _generate_video_cover(resource, output_dir or _get_preview_root())

        guessed_mime, _ = mimetypes.guess_type(resource.file_path)
        if guessed_mime:
            resource.mime_type = guessed_mime

        resource.indexed_at = timezone.now()
        resource.last_synced_at = timezone.now()
        resource.status = 'completed'
        resource.save(
            update_fields=[
                'status', 'file_size', 'modified_at', 'width', 'height',
                'duration_seconds', 'cover_path', 'indexed_at', 'last_synced_at', 'mime_type', 'file_hash',
                'extension', 'updated_at'
            ]
        )
        record_source_index_progress(resource, success=True)
    except subprocess.TimeoutExpired:
        resource.status = 'failed'
        resource.last_error = '处理超时'
        resource.save(update_fields=['status', 'last_error', 'updated_at'])
        record_source_index_progress(resource, success=False)
    except subprocess.CalledProcessError as exc:
        resource.status = 'failed'
        resource.last_error = _format_subprocess_error(exc.stderr)
        resource.save(update_fields=['status', 'last_error', 'updated_at'])
        record_source_index_progress(resource, success=False)
    except Exception as exc:
        resource.status = 'failed'
        resource.last_error = str(exc)[:1000]
        resource.save(update_fields=['status', 'last_error', 'updated_at'])
        record_source_index_progress(resource, success=False)


@db_task()
def index_visual_resource_task(resource_id, output_dir=None):
    return run_index_visual_resource(resource_id, output_dir)


def extract_video_cover_task(video_id, output_dir):
    return index_visual_resource_task(video_id, output_dir)


def run_sync_source_root(source_root_id, queue_index=True, inline_index=False):
    try:
        source_root = SourceRoot.objects.get(id=source_root_id, is_enabled=True)
    except SourceRoot.DoesNotExist:
        return None

    index_runner = run_index_visual_resource if inline_index else None
    return sync_source_root(source_root, queue_index=queue_index, index_runner=index_runner)


@db_task()
def sync_source_root_task(source_root_id, queue_index=True):
    try:
        return run_sync_source_root(source_root_id, queue_index=queue_index, inline_index=False)
    except FileNotFoundError as exc:
        source_root = SourceRoot.objects.filter(id=source_root_id).first()
        if source_root:
            record_source_sync_failure(source_root, str(exc))
        return None
    except Exception as exc:
        source_root = SourceRoot.objects.filter(id=source_root_id).first()
        if source_root:
            record_source_sync_failure(source_root, str(exc))
        raise


def enqueue_source_sync(source_root, queue_index=True):
    if source_root.is_syncing:
        return False
    mark_source_sync_started(source_root)
    sync_source_root_task(source_root.id, queue_index=queue_index)
    return True


@periodic_task(_get_sync_schedule())
def sync_enabled_visual_sources_task():
    from .models import SourceRoot

    summaries = []
    for source_root in SourceRoot.objects.filter(is_enabled=True).order_by('name'):
        try:
            if source_root.is_syncing:
                continue
            mark_source_sync_started(source_root)
            summaries.append(sync_source_root(source_root, queue_index=True))
        except FileNotFoundError as exc:
            record_source_sync_failure(source_root, str(exc))
    return summaries