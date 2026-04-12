import os
import mimetypes
import hashlib
import platform
import subprocess
from pathlib import Path
from datetime import timedelta
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Min, Q
from django.http import FileResponse, Http404, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import SourceRootCreateForm, SourceRootUpdateForm
from .models import Collection, SourceRoot, VisualResource
from .sync import record_source_sync_failure
from .tasks import _open_pillow_image, enqueue_source_sync, run_index_visual_resource, run_sync_source_root

try:
    from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError
except ImportError:
    Image = None
    ImageOps = None
    ImageSequence = None
    UnidentifiedImageError = OSError


if Image is not None:
    _PIL_RESAMPLE = getattr(getattr(Image, 'Resampling', Image), 'LANCZOS', Image.LANCZOS)
else:
    _PIL_RESAMPLE = None


def _guess_content_type(path):
    content_type, _ = mimetypes.guess_type(path)
    return content_type or 'application/octet-stream'


def _build_source_tree(enabled_only=True):
    """Build source root + top-level folder groups for sidebar navigation."""
    tree = []
    source_roots = SourceRoot.objects.all()
    if enabled_only:
        source_roots = source_roots.filter(is_enabled=True)

    for source in source_roots.order_by('name'):
        total = source.resources.count()
        rel_paths = list(source.resources.values_list('relative_path', flat=True).distinct()[:500])
        folder_counts = {}
        for rel in rel_paths:
            if not rel:
                continue
            parts = rel.replace('\\', '/').split('/')
            if len(parts) > 1:
                folder = parts[0]
                folder_counts[folder] = folder_counts.get(folder, 0) + 1
        tree.append({
            'source': source,
            'total': total,
            'folders': sorted(folder_counts.items()),
            'status': _get_source_status(source),
            'progress_percent': int((source.sync_progress_scanned / source.sync_progress_total) * 100) if source.is_syncing and source.sync_progress_total else 0,
            'index_progress_percent': int((source.index_progress_processed / source.index_progress_total) * 100) if source.is_syncing and source.index_progress_total else 0,
        })
    return tree


def _format_sync_label(dt):
    if not dt:
        return '尚未同步'
    local_dt = timezone.localtime(dt)
    return local_dt.strftime('%Y-%m-%d %H:%M')


def _get_source_status(source):
    root_exists = Path(source.root_path).exists()
    sync_minutes = max(1, int(getattr(settings, 'VISUALS_SYNC_MINUTES', 5)))
    stale_cutoff = timezone.now() - timedelta(minutes=sync_minutes * 2)

    if source.is_syncing:
        return {
            'code': 'syncing',
            'label': '扫描中',
            'tone': 'warning',
            'last_synced_label': _format_sync_label(source.sync_started_at or source.last_synced_at),
        }
    if not source.is_enabled:
        return {
            'code': 'disabled',
            'label': '已停用',
            'tone': 'muted',
            'last_synced_label': _format_sync_label(source.last_synced_at),
        }
    if not root_exists:
        return {
            'code': 'missing',
            'label': '目录不可达',
            'tone': 'danger',
            'last_synced_label': _format_sync_label(source.last_synced_at),
        }
    if source.last_sync_error:
        return {
            'code': 'error',
            'label': '同步异常',
            'tone': 'danger',
            'last_synced_label': _format_sync_label(source.last_synced_at),
        }
    if not source.last_synced_at:
        return {
            'code': 'never',
            'label': '等待首次同步',
            'tone': 'warning',
            'last_synced_label': '尚未同步',
        }
    if source.last_synced_at < stale_cutoff:
        return {
            'code': 'stale',
            'label': '同步滞后',
            'tone': 'warning',
            'last_synced_label': _format_sync_label(source.last_synced_at),
        }
    return {
        'code': 'healthy',
        'label': '同步正常',
        'tone': 'ok',
        'last_synced_label': _format_sync_label(source.last_synced_at),
    }


def _open_local_directory_picker():
    if platform.system() != 'Windows':
        raise RuntimeError('当前目录选择器只支持 Windows 本地部署环境。')

    command = [
        'powershell',
        '-NoProfile',
        '-STA',
        '-Command',
        (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dialog.Description = '选择要加入 visuals 的本地目录'; "
            "$dialog.UseDescriptionForTitle = $true; "
            "$dialog.ShowNewFolderButton = $false; "
            "$result = $dialog.ShowDialog(); "
            "if ($result -eq [System.Windows.Forms.DialogResult]::OK) { [Console]::Out.Write($dialog.SelectedPath) }"
        ),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or '目录选择器启动失败。')
    selected_path = (result.stdout or '').strip()
    if not selected_path:
        return None
    return str(Path(selected_path).expanduser().resolve())


def _open_in_file_explorer(target_path):
    if platform.system() != 'Windows':
        raise RuntimeError('当前快捷打开只支持 Windows 本地部署环境。')

    resolved_target = Path(target_path).expanduser().resolve()
    if resolved_target.exists():
        explorer_command = ['explorer', '/select,', str(resolved_target)]
        result = 'selected'
    else:
        parent_path = resolved_target.parent
        if not parent_path.exists():
            raise RuntimeError('资源文件和上级目录都不可用，无法打开资源管理器。')
        explorer_command = ['explorer', str(parent_path)]
        result = 'folder'

    try:
        subprocess.Popen(explorer_command)
    except OSError as exc:
        raise RuntimeError('资源管理器启动失败。') from exc

    return result


def _get_preview_root():
    return Path(getattr(settings, 'VISUALS_PREVIEW_ROOT', Path(settings.MEDIA_ROOT) / 'visuals_previews'))


def _get_preview_cache_root():
    cache_root = _get_preview_root() / 'card_cache'
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


def _get_post_next_url(request, default_url):
    next_url = (request.POST.get('next') or '').strip()
    return next_url or default_url


def _get_home_filters(request):
    return {
        'q': (request.GET.get('q') or '').strip(),
        'type': (request.GET.get('type') or '').strip(),
        'source': (request.GET.get('source') or '').strip(),
        'collection': (request.GET.get('collection') or '').strip(),
        'liked': request.GET.get('liked') == '1',
        'missing': request.GET.get('missing') == '1',
        'status': (request.GET.get('status') or '').strip(),
        'folder': (request.GET.get('folder') or '').strip(),
    }


def _build_home_queryset(filters):
    query = filters['q']
    resource_type = filters['type']
    source_id = filters['source']
    collection_id = filters['collection']
    liked_only = filters['liked']
    missing_only = filters['missing']
    status = filters['status']
    folder = filters['folder']

    resources = VisualResource.objects.select_related('source_root').prefetch_related('tags', 'collections').all()

    meili_hit_ids = None
    if query:
        try:
            import meilisearch
            from django.conf import settings as _s
            client = meilisearch.Client(
                getattr(_s, 'MEILI_URL', 'http://127.0.0.1:7700'),
                getattr(_s, 'MEILI_KEY', 'dq49aaqs-RYHbIfKGMOFJRrfco3jP-0Ubj4gcX9caBc'),
            )
            result = client.index('visuals_resources').search(query, {'limit': 200})
            meili_hit_ids = [hit['id'] for hit in result['hits']]
        except Exception as exc:
            print(f"Visuals Meilisearch unavailable, fallback to ORM: {exc}")

    if meili_hit_ids:
        meili_resources = resources.filter(id__in=meili_hit_ids)
        if meili_resources.exists():
            resources = meili_resources
        else:
            resources = resources.filter(
                Q(title__icontains=query)
                | Q(file_path__icontains=query)
                | Q(relative_path__icontains=query)
                | Q(tags__name__icontains=query)
                | Q(collections__name__icontains=query)
            )
    elif query:
        resources = resources.filter(
            Q(title__icontains=query)
            | Q(file_path__icontains=query)
            | Q(relative_path__icontains=query)
            | Q(tags__name__icontains=query)
            | Q(collections__name__icontains=query)
        )

    if resource_type:
        resources = resources.filter(resource_type=resource_type)
    if source_id:
        resources = resources.filter(source_root_id=source_id)
    if collection_id:
        resources = resources.filter(collections__id=collection_id)
    if liked_only:
        resources = resources.filter(is_liked=True)
    if missing_only:
        resources = resources.filter(is_missing=True)
    if status:
        resources = resources.filter(status=status)
    if folder and source_id:
        resources = resources.filter(
            Q(relative_path__startswith=folder + '/') | Q(relative_path__startswith=folder + '\\')
        )

    return resources.distinct().order_by('-is_liked', '-created_at', '-id')


def _build_home_querystring(filters, page=None, extra_params=None):
    params = []
    ordered_keys = ['q', 'type', 'source', 'collection', 'status', 'folder']
    for key in ordered_keys:
        value = filters.get(key)
        if value:
            params.append((key, value))
    if filters.get('liked'):
        params.append(('liked', '1'))
    if filters.get('missing'):
        params.append(('missing', '1'))
    if page is not None:
        params.append(('page', str(page)))
    if extra_params:
        for key, value in extra_params.items():
            if value is None or value == '':
                continue
            params.append((key, str(value)))
    return urlencode(params)


def _build_home_url(filters, page=None, anchor=None):
    url = reverse('visuals:home')
    querystring = _build_home_querystring(filters, page=page)
    if querystring:
        url += '?' + querystring
    if anchor:
        url += '#' + anchor
    return url


def _build_resource_detail_url(resource_id, filters, page, return_card):
    url = reverse('visuals:resource_detail', args=[resource_id])
    querystring = _build_home_querystring(filters, page=page, extra_params={'return_card': return_card})
    if querystring:
        url += '?' + querystring
    return url


def _build_detail_navigation_context(resource, filters, page_hint=None, include_back_url=False):
    resource_ids = list(_build_home_queryset(filters).values_list('id', flat=True))
    if not resource_ids or resource.id not in resource_ids:
        back_page = page_hint if page_hint and page_hint > 0 else 1
        back_url = _build_home_url(filters, page=back_page, anchor=f'card-{resource.id}') if include_back_url else reverse('visuals:home')
        return {
            'back_url': back_url,
            'previous_url': None,
            'next_url': None,
        }

    current_index = resource_ids.index(resource.id)
    current_page = (current_index // 24) + 1

    def build_neighbor_url(neighbor_index):
        if neighbor_index < 0 or neighbor_index >= len(resource_ids):
            return None
        neighbor_id = resource_ids[neighbor_index]
        neighbor_page = (neighbor_index // 24) + 1
        return _build_resource_detail_url(neighbor_id, filters, page=neighbor_page, return_card=neighbor_id)

    back_url = _build_home_url(filters, page=current_page, anchor=f'card-{resource.id}') if include_back_url else reverse('visuals:home')
    return {
        'back_url': back_url,
        'previous_url': build_neighbor_url(current_index - 1),
        'next_url': build_neighbor_url(current_index + 1),
    }


def _build_preview_signature(resource, source_path):
    stat_result = os.stat(source_path)
    signature_seed = (
        f'{resource.id}:{source_path}:{int(stat_result.st_mtime)}:{stat_result.st_size}:'
        f'{int(resource.updated_at.timestamp()) if resource.updated_at else 0}'
    )
    return hashlib.sha1(signature_seed.encode('utf-8')).hexdigest()[:20]


def _get_cached_preview_path(resource, source_path, max_size=(640, 640)):
    if Image is None or ImageOps is None or ImageSequence is None:
        return source_path

    cache_root = _get_preview_cache_root()
    cache_name = f'{resource.id}-{_build_preview_signature(resource, source_path)}.jpg'
    cache_path = cache_root / cache_name
    if cache_path.exists():
        return str(cache_path)

    for stale_file in cache_root.glob(f'{resource.id}-*.jpg'):
        if stale_file != cache_path:
            stale_file.unlink(missing_ok=True)

    try:
        with _open_pillow_image(source_path) as image:
            if getattr(image, 'is_animated', False):
                frame = next(ImageSequence.Iterator(image)).copy()
            else:
                frame = image.copy()

        thumbnail = ImageOps.exif_transpose(frame)
        if thumbnail.mode in {'RGBA', 'LA', 'P'}:
            rgba_image = thumbnail.convert('RGBA')
            background = Image.new('RGB', rgba_image.size, '#f8f1e6')
            background.paste(rgba_image, mask=rgba_image.split()[-1])
            thumbnail = background
        elif thumbnail.mode != 'RGB':
            thumbnail = thumbnail.convert('RGB')

        thumbnail.thumbnail(max_size, _PIL_RESAMPLE)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        thumbnail.save(cache_path, format='JPEG', quality=82, optimize=True)
        thumbnail.close()
        return str(cache_path)
    except (FileNotFoundError, OSError, ValueError, StopIteration, UnidentifiedImageError):
        return source_path


def _resolve_preview_path(resource, variant='full'):
    if resource.resource_type in {'image', 'gif'}:
        preview_path = resource.file_path
    elif resource.resource_type == 'video' and resource.cover_path:
        preview_path = resource.cover_path
    else:
        raise Http404('当前资源没有可用预览')

    if not preview_path or not os.path.exists(preview_path):
        raise Http404('预览文件不存在')

    if variant == 'card':
        preview_path = _get_cached_preview_path(resource, preview_path)

    return preview_path


def _build_home_context(request, source_form=None, edit_form=None, edit_source=None):
    filters = _get_home_filters(request)
    edit_source_id = (request.GET.get('edit_source') or '').strip()
    resources = _build_home_queryset(filters)
    paginator = Paginator(resources, 24)
    page_obj = paginator.get_page(request.GET.get('page'))
    for resource in page_obj.object_list:
        resource.detail_url = _build_resource_detail_url(resource.id, filters, page_obj.number, resource.id)

    type_count_map = {
        row['resource_type']: row['cnt']
        for row in VisualResource.objects.values('resource_type').annotate(cnt=Count('id'))
    }
    type_list = [
        {'value': value, 'label': label, 'count': type_count_map.get(value, 0)}
        for value, label in VisualResource.RESOURCE_TYPE_CHOICES
    ]

    return {
        'page_obj': page_obj,
        'resources': page_obj.object_list,
        'sources': SourceRoot.objects.filter(is_enabled=True).order_by('name'),
        'collections': Collection.objects.annotate(resource_count=Count('resources')).order_by('name'),
        'resource_type_choices': VisualResource.RESOURCE_TYPE_CHOICES,
        'status_choices': VisualResource.STATUS_CHOICES,
        'source_tree': _build_source_tree(enabled_only=True),
        'type_list': type_list,
        'current_filters': {
            'q': filters['q'],
            'type': filters['type'],
            'source': filters['source'],
            'collection': filters['collection'],
            'edit_source': edit_source_id,
            'liked': filters['liked'],
            'missing': filters['missing'],
            'status': filters['status'],
            'folder': filters['folder'],
        },
        'stats': {
            'total': VisualResource.objects.count(),
            'liked': VisualResource.objects.filter(is_liked=True).count(),
            'missing': VisualResource.objects.filter(is_missing=True).count(),
            'ready': VisualResource.objects.filter(status='completed').count(),
        },
        'sync_summary': {
            'last_synced_label': _format_sync_label(
                SourceRoot.objects.filter(last_synced_at__isnull=False).order_by('-last_synced_at').values_list('last_synced_at', flat=True).first()
            ),
            'enabled_count': SourceRoot.objects.filter(is_enabled=True).count(),
            'error_count': SourceRoot.objects.exclude(last_sync_error='').count(),
            'syncing_count': SourceRoot.objects.filter(is_syncing=True).count(),
        },
    }


def _build_sources_context(request, source_form=None, edit_form=None, edit_source=None):
    edit_source_id = (request.GET.get('edit_source') or '').strip()
    selected_edit_source = edit_source
    if not selected_edit_source and edit_source_id:
        selected_edit_source = SourceRoot.objects.filter(id=edit_source_id).first()

    if selected_edit_source and not edit_form:
        edit_form = SourceRootUpdateForm(initial={
            'name': selected_edit_source.name,
            'root_path': selected_edit_source.root_path,
            'is_enabled': selected_edit_source.is_enabled,
        })

    return {
        'source_tree': _build_source_tree(enabled_only=False),
        'source_form': source_form or SourceRootCreateForm(),
        'edit_source': selected_edit_source,
        'edit_source_form': edit_form,
        'sync_summary': {
            'last_synced_label': _format_sync_label(
                SourceRoot.objects.filter(last_synced_at__isnull=False).order_by('-last_synced_at').values_list('last_synced_at', flat=True).first()
            ),
            'enabled_count': SourceRoot.objects.filter(is_enabled=True).count(),
            'error_count': SourceRoot.objects.exclude(last_sync_error='').count(),
            'total_count': SourceRoot.objects.count(),
            'syncing_count': SourceRoot.objects.filter(is_syncing=True).count(),
        },
        'library_stats': {
            'total_resources': VisualResource.objects.count(),
            'missing_resources': VisualResource.objects.filter(is_missing=True).count(),
        },
        'current_edit_source_id': str(selected_edit_source.id) if selected_edit_source else '',
        'sources_page_url': reverse('visuals:sources'),
        'sources_progress_url': reverse('visuals:sources_progress'),
    }


def visuals_view(request):
    return render(request, 'visuals/index.html', _build_home_context(request))


def source_roots_view(request):
    return render(request, 'visuals/sources.html', _build_sources_context(request))


def sources_progress(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    source_entries = []
    for source in SourceRoot.objects.all().order_by('name'):
        status = _get_source_status(source)
        progress_percent = int((source.sync_progress_scanned / source.sync_progress_total) * 100) if source.is_syncing and source.sync_progress_total else 0
        source_entries.append({
            'id': source.id,
            'is_syncing': source.is_syncing,
            'status_label': status['label'],
            'status_tone': status['tone'],
            'last_synced_label': status['last_synced_label'],
            'phase': source.sync_phase or '',
            'scanned': source.sync_progress_scanned,
            'total': source.sync_progress_total,
            'percent': progress_percent,
            'index_total': source.index_progress_total,
            'index_processed': source.index_progress_processed,
            'index_completed': source.index_progress_completed,
            'index_failed': source.index_progress_failed,
            'index_percent': int((source.index_progress_processed / source.index_progress_total) * 100) if source.is_syncing and source.index_progress_total else 0,
            'current_path': source.sync_current_path or '',
            'last_sync_created': source.last_sync_created,
            'last_sync_updated': source.last_sync_updated,
            'last_sync_missing': source.last_sync_missing,
            'last_sync_error': source.last_sync_error or '',
        })

    return JsonResponse({
        'syncing_count': sum(1 for entry in source_entries if entry['is_syncing']),
        'sources': source_entries,
    })


def create_source_root(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    form = SourceRootCreateForm(request.POST)
    if not form.is_valid():
        messages.error(request, '资源源未创建，请先修正目录信息。')
        return render(request, 'visuals/sources.html', _build_sources_context(request, source_form=form), status=400)

    resolved_path = form.cleaned_data['root_path']
    source_name = form.cleaned_data['name'] or Path(resolved_path).name
    is_enabled = form.cleaned_data['is_enabled']

    existing_by_name = SourceRoot.objects.filter(name=source_name).exclude(root_path=resolved_path).first()
    if existing_by_name:
        form.add_error('name', '这个资源源名称已经被其他目录占用。')
        return render(request, 'visuals/sources.html', _build_sources_context(request, source_form=form), status=400)

    source_root, created = SourceRoot.objects.get_or_create(
        root_path=resolved_path,
        defaults={'name': source_name, 'is_enabled': is_enabled},
    )
    changed_fields = []
    if source_root.name != source_name:
        source_root.name = source_name
        changed_fields.append('name')
    if source_root.is_enabled != is_enabled:
        source_root.is_enabled = is_enabled
        changed_fields.append('is_enabled')
    if changed_fields:
        changed_fields.append('updated_at')
        source_root.save(update_fields=changed_fields)

    verb = '已新增' if created else '已更新'
    if is_enabled:
        enqueue_source_sync(source_root, queue_index=True)
        messages.success(request, f'{verb}资源源 {source_root.name}，后台扫描已开始。')
    else:
        messages.success(request, f'{verb}资源源 {source_root.name}，当前为停用状态，未执行扫描。')
    return redirect(_get_post_next_url(request, reverse('visuals:sources')))


def update_source_root(request, source_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    source_root = get_object_or_404(SourceRoot, id=source_id)
    form = SourceRootUpdateForm(request.POST)
    if not form.is_valid():
        messages.error(request, f'资源源 {source_root.name} 未更新，请先修正目录信息。')
        return render(
            request,
            'visuals/sources.html',
            _build_sources_context(request, edit_form=form, edit_source=source_root),
            status=400,
        )

    resolved_path = form.cleaned_data['root_path']
    source_name = form.cleaned_data['name'] or Path(resolved_path).name
    is_enabled = form.cleaned_data['is_enabled']

    existing_by_name = SourceRoot.objects.filter(name=source_name).exclude(id=source_root.id).first()
    if existing_by_name:
        form.add_error('name', '这个资源源名称已经被其他目录占用。')
        return render(
            request,
            'visuals/sources.html',
            _build_sources_context(request, edit_form=form, edit_source=source_root),
            status=400,
        )

    path_changed = source_root.root_path != resolved_path
    changed_fields = []
    if source_root.name != source_name:
        source_root.name = source_name
        changed_fields.append('name')
    if source_root.root_path != resolved_path:
        source_root.root_path = resolved_path
        changed_fields.append('root_path')
    if source_root.is_enabled != is_enabled:
        source_root.is_enabled = is_enabled
        changed_fields.append('is_enabled')
    if changed_fields:
        changed_fields.append('updated_at')
        source_root.save(update_fields=changed_fields)

    if is_enabled and not Path(resolved_path).exists():
        form.add_error('root_path', '目录当前不可达，资源源已更新但暂时无法扫描。')
        return render(
            request,
            'visuals/sources.html',
            _build_sources_context(request, edit_form=form, edit_source=source_root),
            status=400,
        )

    if changed_fields:
        detail = '后台扫描已开始。' if is_enabled else '资源源已停用，未执行同步。'
        if path_changed:
            detail = '目录已更新，' + detail
        if is_enabled:
            enqueue_source_sync(source_root, queue_index=True)
        messages.success(request, f'资源源 {source_root.name} 已更新：{detail}')
    else:
        messages.info(request, f'资源源 {source_root.name} 没有变更。')

    return redirect(_get_post_next_url(request, reverse('visuals:sources')))


def pick_source_root(request):
    if request.method != 'GET':
        return HttpResponseNotAllowed(['GET'])

    try:
        selected_path = _open_local_directory_picker()
    except RuntimeError as exc:
        return JsonResponse({'ok': False, 'message': str(exc)}, status=500)

    if not selected_path:
        return JsonResponse({'ok': False, 'message': '已取消选择。'}, status=400)
    return JsonResponse({'ok': True, 'path': selected_path})


def delete_source_root(request, source_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    source_root = get_object_or_404(SourceRoot, id=source_id)
    source_name = source_root.name
    removed_count = source_root.resources.count()
    source_root.resources.all().delete()
    source_root.delete()
    messages.success(request, f'已移除资源源 {source_name} 的 {removed_count} 条索引记录，本地文件未删除。')
    return redirect(request.POST.get('next') or 'visuals:home')


def resource_detail(request, resource_id):
    resource = get_object_or_404(
        VisualResource.objects.select_related('source_root').prefetch_related('tags', 'collections'),
        id=resource_id,
    )
    filters = _get_home_filters(request)
    page_hint = request.GET.get('page')
    try:
        page_hint = int(page_hint)
    except (TypeError, ValueError):
        page_hint = None
    has_listing_context = bool(page_hint or request.GET.get('return_card') or any(filters.values()))
    navigation_context = _build_detail_navigation_context(
        resource,
        filters,
        page_hint=page_hint,
        include_back_url=has_listing_context,
    )
    source_status = _get_source_status(resource.source_root) if resource.source_root else None
    preview_modal_url = None
    preview_modal_kind = None
    if not resource.is_missing:
        if resource.resource_type == 'video':
            preview_modal_url = reverse('visuals:stream_video', args=[resource.id])
            preview_modal_kind = 'video'
        elif resource.has_preview:
            preview_modal_url = reverse('visuals:preview_resource', args=[resource.id])
            preview_modal_kind = 'image'
    return render(request, 'visuals/detail.html', {
        'resource': resource,
        'source_status': source_status,
        'resource_last_synced_label': _format_sync_label(resource.last_synced_at),
        'sources_page_url': reverse('visuals:sources'),
        'preview_modal_url': preview_modal_url,
        'preview_modal_kind': preview_modal_kind,
        'back_url': navigation_context['back_url'],
        'previous_resource_url': navigation_context['previous_url'],
        'next_resource_url': navigation_context['next_url'],
    })


def open_resource_in_explorer(request, resource_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    resource = get_object_or_404(VisualResource, id=resource_id)
    next_url = _get_post_next_url(request, reverse('visuals:resource_detail', args=[resource.id]))

    try:
        open_result = _open_in_file_explorer(resource.file_path)
    except RuntimeError as exc:
        messages.error(request, str(exc))
    else:
        if open_result == 'selected':
            messages.success(request, '已在资源管理器中定位到当前文件。')
        else:
            messages.warning(request, '当前文件已不可用，已打开其所在目录。')
    return redirect(next_url)


def preview_resource(request, resource_id):
    resource = get_object_or_404(VisualResource, id=resource_id)
    variant = (request.GET.get('variant') or 'full').strip().lower()
    preview_path = _resolve_preview_path(resource, variant=variant)
    response = FileResponse(open(preview_path, 'rb'), content_type=_guess_content_type(preview_path))
    response['Cache-Control'] = 'public, max-age=86400'
    return response


def stream_video(request, video_id):
    resource = get_object_or_404(VisualResource, id=video_id, resource_type='video')
    if os.path.exists(resource.file_path):
        return FileResponse(open(resource.file_path, 'rb'), content_type=_guess_content_type(resource.file_path))
    raise Http404('视频文件在本地硬盘上找不到了')


def toggle_like(request, resource_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])
    resource = get_object_or_404(VisualResource, id=resource_id)
    resource.is_liked = not resource.is_liked
    resource.save(update_fields=['is_liked', 'updated_at'])
    return redirect(request.POST.get('next') or 'visuals:home')


def batch_action(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    action = (request.POST.get('action') or '').strip()
    resource_ids = request.POST.getlist('resource_ids')
    next_url = request.POST.get('next') or 'visuals:home'

    if not resource_ids or not action:
        return redirect(next_url)

    resources = VisualResource.objects.filter(id__in=resource_ids)

    if action == 'like':
        resources.update(is_liked=True)

    elif action == 'unlike':
        resources.update(is_liked=False)

    elif action == 'add_tag':
        from gallery.models import Tag
        tag_name = (request.POST.get('tag_name') or '').strip()
        if tag_name:
            tag, _ = Tag.objects.get_or_create(name=tag_name)
            for r in resources:
                r.tags.add(tag)

    elif action == 'remove_tag':
        from gallery.models import Tag
        tag_name = (request.POST.get('tag_name') or '').strip()
        if tag_name:
            try:
                tag = Tag.objects.get(name=tag_name)
                for r in resources:
                    r.tags.remove(tag)
            except Tag.DoesNotExist:
                pass

    elif action == 'add_collection':
        collection_name = (request.POST.get('collection_name') or '').strip()
        if collection_name:
            collection, _ = Collection.objects.get_or_create(name=collection_name)
            for r in resources:
                r.collections.add(collection)

    elif action == 'reindex':
        from .tasks import index_visual_resource_task
        for r in resources:
            r.status = 'pending'
            r.save(update_fields=['status', 'updated_at'])
            index_visual_resource_task(r.id)

    elif action == 'remove_from_library':
        removed_count = resources.count()
        resources.delete()
        messages.success(request, f'已从资源库移除 {removed_count} 条索引记录，本地文件未删除。')

    return redirect(next_url)


def sync_all_sources_now(request):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    started_count = 0
    for source_root in SourceRoot.objects.filter(is_enabled=True).order_by('name'):
        if Path(source_root.root_path).exists() and enqueue_source_sync(source_root, queue_index=True):
            started_count += 1
        elif not Path(source_root.root_path).exists():
            record_source_sync_failure(source_root, f'资源根目录不存在: {source_root.root_path}')

    if started_count:
        messages.success(request, f'已启动 {started_count} 个资源源的后台扫描，页面会自动刷新显示进度。')
    else:
        messages.warning(request, '当前没有可启动的资源源扫描任务。')
    return redirect(request.POST.get('next') or 'visuals:home')


def sync_source_now(request, source_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    source_root = get_object_or_404(SourceRoot, id=source_id)
    if not Path(source_root.root_path).exists():
        record_source_sync_failure(source_root, f'资源根目录不存在: {source_root.root_path}')
        messages.error(request, f'资源源 {source_root.name} 的目录不可达，未能完成同步。')
    else:
        if enqueue_source_sync(source_root, queue_index=True):
            messages.success(request, f'{source_root.name} 已加入后台扫描，页面会自动刷新显示进度。')
        else:
            messages.warning(request, f'资源源 {source_root.name} 已有扫描任务在进行。')
    return redirect(request.POST.get('next') or 'visuals:home')


def sync_resource_now(request, resource_id):
    if request.method != 'POST':
        return HttpResponseNotAllowed(['POST'])

    resource = get_object_or_404(VisualResource.objects.select_related('source_root'), id=resource_id)
    if resource.source_root_id:
        try:
            run_sync_source_root(resource.source_root_id, queue_index=False, inline_index=False)
        except FileNotFoundError as exc:
            if resource.source_root:
                record_source_sync_failure(resource.source_root, str(exc))
            messages.error(request, '所属资源源目录不可达，无法刷新当前资源。')
            next_url = request.POST.get('next')
            if next_url:
                return redirect(next_url)
            return redirect('visuals:resource_detail', resource_id=resource.id)
    resource.status = 'pending'
    resource.last_error = ''
    resource.save(update_fields=['status', 'last_error', 'updated_at'])
    run_index_visual_resource(resource.id)
    resource.refresh_from_db(fields=['status', 'last_error', 'last_synced_at', 'indexed_at'])
    if resource.status == 'completed':
        messages.success(request, f'{resource.title} 已完成重新同步。')
    else:
        messages.error(request, f'{resource.title} 同步失败：{resource.last_error or "未知错误"}')
    next_url = request.POST.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('visuals:resource_detail', resource_id=resource.id)


def duplicates(request):
    page_size = 10
    dupe_hashes = (
        VisualResource.objects
        .filter(file_hash__gt='')
        .values('file_hash')
        .annotate(count=Count('id'), first_id=Min('id'))
        .filter(count__gt=1)
        .order_by('-count', 'first_id')
    )
    paginator = Paginator(dupe_hashes, page_size)
    page_obj = paginator.get_page(request.GET.get('page'))
    page_entries = list(page_obj.object_list)

    page_hashes = [entry['file_hash'] for entry in page_entries]
    resources_by_hash = {file_hash: [] for file_hash in page_hashes}
    if page_hashes:
        for resource in (
            VisualResource.objects
            .select_related('source_root')
            .filter(file_hash__in=page_hashes)
            .order_by('file_hash', 'created_at')
        ):
            resources_by_hash.setdefault(resource.file_hash, []).append(resource)

    groups = []
    for index, entry in enumerate(page_entries, start=page_obj.start_index()):
        groups.append({
            'display_index': index,
            'hash': entry['file_hash'],
            'count': entry['count'],
            'resources': resources_by_hash.get(entry['file_hash'], []),
        })

    return render(request, 'visuals/duplicates.html', {
        'groups': groups,
        'total_groups': paginator.count,
        'page_obj': page_obj,
        'page_size': page_size,
    })

