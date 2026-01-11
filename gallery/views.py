import os
import uuid
import json
import re
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Q, Count, Case, When, IntegerField, Max, Prefetch
from django.core.paginator import Paginator
from django.views.decorators.http import require_GET, require_POST
from django.core.cache import cache
from django.template.loader import render_to_string
from .models import ImageItem, PromptGroup, Tag, AIModel, ReferenceItem
from .forms import PromptGroupForm
from .ai_utils import search_similar_images

# === 引入 Service 层 ===
from .services import (
    get_temp_dir, 
    calculate_file_hash, 
    trigger_background_processing,
    confirm_upload_images
)

# ==========================================
# 辅助函数
# ==========================================
def get_tags_bar_data():
    """获取侧边栏标签数据（复用逻辑）"""
    ai_model_names = list(AIModel.objects.values_list('name', flat=True))
    return Tag.objects.filter(promptgroup__isnull=False).distinct().annotate(
        use_count=Count('promptgroup'),
        is_model=Case(
            When(name__in=ai_model_names, then=1),
            default=2,
            output_field=IntegerField(),
        )
    ).order_by('is_model', '-use_count')

# 【核心修改】智能 Tag 差异对比函数
def generate_diff_html(base_text, compare_text):
    """
    比较 compare_text (其他版本) 相对于 base_text (当前版本) 的差异。
    只返回差异部分的 HTML。
    """
    if base_text is None: base_text = ""
    if compare_text is None: compare_text = ""
    
    # 1. 智能拆分 Tag (支持 英文逗号, 中文逗号，换行符)
    def parse_tags_to_dict(text):
        # 正则分割：逗号(,)、中文逗号(，)、换行(\n)
        parts = re.split(r'[,\uff0c\n]+', text)
        # 生成 {小写key: 原始写法value} 的映射，用于忽略大小写比对但展示原始拼写
        return {p.strip().lower(): p.strip() for p in parts if p.strip()}

    base_map = parse_tags_to_dict(base_text)
    comp_map = parse_tags_to_dict(compare_text)
    
    base_keys = set(base_map.keys())
    comp_keys = set(comp_map.keys())
    
    # 2. 提取差异集合
    # 新增的 = 对方有 - 我没有
    added_keys = comp_keys - base_keys
    # 移除的 = 我有 - 对方没有
    removed_keys = base_keys - comp_keys
    
    # 如果没有检测到任何 Tag 差异
    if not added_keys and not removed_keys:
        return '<span class="no-diff">无提示词差异</span>'
    
    html_parts = []
    
    # 3. 生成 HTML
    # 策略：先展示【新增】的（通常用户更关心这个版本多了什么），再展示【减少】的
    
    # A. 展示新增 (Green)
    for k in added_keys:
        val = comp_map[k]
        # 截断超长 Tag 防止破坏布局
        display_val = (val[:20] + '..') if len(val) > 20 else val
        html_parts.append(
            f'<span class="diff-tag diff-add" title="相对于当前版本，此处新增了: {val}">'
            f'<i class="bi bi-plus"></i>{display_val}</span>'
        )
        
    # B. 展示移除 (Red/Grey)
    for k in removed_keys:
        val = base_map[k]
        display_val = (val[:20] + '..') if len(val) > 20 else val
        html_parts.append(
            f'<span class="diff-tag diff-rem" title="相对于当前版本，此处移除了: {val}">'
            f'<i class="bi bi-dash"></i>{display_val}</span>'
        )
        
    return "".join(html_parts)
# ==========================================
# 视图函数
# ==========================================

def home(request):
    queryset = PromptGroup.objects.all()
    query = request.GET.get('q')
    filter_type = request.GET.get('filter')
    search_id = request.GET.get('search_id')

    # === 1. 处理以图搜图提交 (POST) -> 转为 GET ===
    if request.method == 'POST' and request.FILES.get('search_image'):
        try:
            search_file = request.FILES['search_image']
            similar_images = search_similar_images(search_file, ImageItem.objects.all(), top_k=50)
            
            if not similar_images:
                messages.info(request, "未找到相似图片")
                return redirect('home')
            
            search_uuid = str(uuid.uuid4())
            cache_data = [{'id': img.id, 'score': getattr(img, 'similarity_score', 0)} for img in similar_images]
            cache_key = f"home_search_{search_uuid}"
            cache.set(cache_key, cache_data, 3600)
            
            return redirect(f"/?search_id={search_uuid}")
                
        except Exception as e:
            print(f"Search error: {e}")
            messages.error(request, "搜索过程中发生错误")
            return redirect('home')

    # === 2. 处理以图搜图结果展示 (GET) ===
    if search_id:
        cache_key = f"home_search_{search_id}"
        cached_data = cache.get(cache_key)
        
        if cached_data:
            ids = [item['id'] for item in cached_data]
            id_score_map = {item['id']: item['score'] for item in cached_data}
            
            images_list = list(ImageItem.objects.filter(id__in=ids))
            objects_dict = {img.id: img for img in images_list}
            
            restored_images = []
            for img_id in ids:
                if img_id in objects_dict:
                    obj = objects_dict[img_id]
                    obj.similarity_score = id_score_map.get(img_id, 0)
                    restored_images.append(obj)
            
            tags_bar = get_tags_bar_data()

            if restored_images:
                return render(request, 'gallery/liked_images.html', {
                    'page_obj': restored_images,
                    'search_query': '全库以图搜图结果',
                    'search_mode': 'image',
                    'is_home_search': True,
                    'current_search_id': search_id,
                    'tags_bar': tags_bar
                })
        else:
            messages.warning(request, "搜索结果已过期，请重新搜索")

    # === 常规文本搜索 ===
    if query:
        queryset = queryset.filter(
            Q(title__icontains=query) |
            Q(prompt_text__icontains=query) |
            Q(prompt_text_zh__icontains=query) |
            Q(tags__name__icontains=query)
        ).distinct()
    
    if filter_type == 'liked':
        queryset = queryset.filter(is_liked=True)

    # === 版本去重与计数逻辑 ===
    version_counts = {}
    if not query and not filter_type and not search_id:
        group_stats = PromptGroup.objects.values('group_id').annotate(
            latest_id=Max('id'),
            count=Count('id')
        )
        latest_ids = [s['latest_id'] for s in group_stats]
        version_counts = {s['latest_id']: s['count'] for s in group_stats}
        queryset = queryset.filter(id__in=latest_ids)

    tags_bar = get_tags_bar_data()
    paginator = Paginator(queryset, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    total_groups_count = PromptGroup.objects.values('group_id').distinct().count()

    for group in page_obj:
        group.version_count = version_counts.get(group.id, 0)

    return render(request, 'gallery/home.html', {
        'page_obj': page_obj,
        'search_query': query,
        'current_filter': filter_type,
        'tags_bar': tags_bar,
        'total_groups_count': total_groups_count,
    })


def liked_images_gallery(request):
    queryset = ImageItem.objects.filter(is_liked=True).order_by('-id')
    search_mode = 'text'
    query_text = request.GET.get('q')
    search_id = request.GET.get('search_id') 
    
    if request.method == 'POST' and request.FILES.get('image_query'):
        try:
            uploaded_file = request.FILES['image_query']
            results = search_similar_images(uploaded_file, queryset) 
            
            search_uuid = str(uuid.uuid4())
            cache_data = [{'id': img.id, 'score': getattr(img, 'similarity_score', 0)} for img in results]
            
            cache_key = f"liked_search_{search_uuid}"
            cache.set(cache_key, cache_data, 3600)
            
            return redirect(f"/liked-images/?search_id={search_uuid}")
            
        except Exception as e:
            messages.error(request, "搜索失败")
            return redirect('liked_images_gallery')

    if search_id:
        cache_key = f"liked_search_{search_id}"
        cached_data = cache.get(cache_key)
        
        if cached_data:
            ids = [item['id'] for item in cached_data]
            id_score_map = {item['id']: item['score'] for item in cached_data}
            
            images_list = list(ImageItem.objects.filter(id__in=ids))
            objects_dict = {img.id: img for img in images_list}
            
            queryset = []
            for img_id in ids:
                if img_id in objects_dict:
                    obj = objects_dict[img_id]
                    obj.similarity_score = id_score_map.get(img_id, 0)
                    queryset.append(obj)
            
            search_mode = 'image'
            query_text = "按图片搜索结果"
        else:
             messages.warning(request, "搜索已过期")
    
    elif query_text:
        queryset = queryset.filter(
            Q(group__title__icontains=query_text) |
            Q(group__prompt_text__icontains=query_text) |
            Q(group__tags__name__icontains=query_text)
        ).distinct()
    
    tags_bar = get_tags_bar_data()
    paginator = Paginator(queryset, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'gallery/liked_images.html', {
        'page_obj': page_obj,
        'search_query': query_text,
        'search_mode': search_mode,
        'is_home_search': False,
        'current_search_id': search_id,
        'tags_bar': tags_bar
    })


def detail(request, pk):
    # 【核心修改】Prefetch 预取时按 ID 倒序，确保最新图在最前
    group = get_object_or_404(
        PromptGroup.objects.prefetch_related(
            'tags', 
            Prefetch('images', queryset=ImageItem.objects.order_by('-id')),
            'references'
        ), 
        pk=pk
    )
    
    tags_list = list(group.tags.all())
    model_name = group.model_info
    if model_name:
        tags_list.sort(key=lambda t: 0 if t.name == model_name else 1)
    
    all_tags = Tag.objects.annotate(usage_count=Count('promptgroup')).order_by('-usage_count', 'name')[:500]

    # 【修改】获取同系列其他版本，并计算差异
    siblings_qs = PromptGroup.objects.filter(
        group_id=group.group_id
    ).exclude(pk=group.pk).order_by('-created_at')
    
    siblings = []
    current_prompt = group.prompt_text or ""
    
    for sib in siblings_qs:
        sib_prompt = sib.prompt_text or ""
        # 动态添加 diff_html 属性供模板使用
        # 这里计算：sibling 相对 current 的差异
        sib.diff_html = generate_diff_html(current_prompt, sib_prompt)
        siblings.append(sib)

    related_groups = PromptGroup.objects.filter(
        tags__in=group.tags.all()
    ).exclude(pk=pk).distinct()[:4]
    
    tags_bar = get_tags_bar_data()

    return render(request, 'gallery/detail.html', {
        'group': group,
        'sorted_tags': tags_list,
        'all_tags': all_tags,
        'siblings': siblings,
        'related_groups': related_groups,
        'tags_bar': tags_bar,
        'search_query': request.GET.get('q')
    })


def upload(request):
    if request.method == 'POST':
        prompt_text = request.POST.get('prompt_text', '')
        prompt_text_zh = request.POST.get('prompt_text_zh', '')
        negative_prompt = request.POST.get('negative_prompt', '')
        title = request.POST.get('title', '') or '未命名组'
        model_id = request.POST.get('model_info')
        
        model_name_str = ""
        if model_id:
            try:
                model_instance = AIModel.objects.get(id=model_id)
                model_name_str = model_instance.name
            except AIModel.DoesNotExist:
                pass

        group = PromptGroup.objects.create(
            title=title,
            prompt_text=prompt_text,
            prompt_text_zh=prompt_text_zh,
            negative_prompt=negative_prompt,
            model_info=model_name_str,
        )
        
        selected_tags = request.POST.getlist('tags')
        for tag_val in selected_tags:
            tag_val = tag_val.strip()
            if not tag_val: continue
            if tag_val.isdigit():
                try:
                    group.tags.add(Tag.objects.get(id=int(tag_val)))
                except Tag.DoesNotExist:
                    pass
            else:
                tag, _ = Tag.objects.get_or_create(name=tag_val)
                group.tags.add(tag)
        
        if model_name_str:
            m_tag, _ = Tag.objects.get_or_create(name=model_name_str)
            group.tags.add(m_tag)

        created_image_ids = []
        
        # 处理本地文件
        direct_files = request.FILES.getlist('upload_images')
        for f in direct_files:
            img_item = ImageItem(group=group, image=f)
            img_item.save()
            created_image_ids.append(img_item.id)

        # 处理服务器暂存文件
        batch_id = request.POST.get('batch_id')
        server_file_names = request.POST.getlist('selected_files')
        
        if batch_id and server_file_names:
            temp_ids = confirm_upload_images(batch_id, server_file_names, group)
            created_image_ids.extend(temp_ids)
            
        # 处理参考图
        ref_files = request.FILES.getlist('upload_references')
        for rf in ref_files:
            ReferenceItem.objects.create(group=group, image=rf)

        if not created_image_ids:
            # messages.warning(request, "虽然发布了作品，但未上传任何生成图。"
            pass
        else:
            trigger_background_processing(created_image_ids)
            messages.success(request, f"成功发布！包含 {len(created_image_ids)} 张图片，系统正在后台处理索引。")

        # 判断是否为 AJAX (上传模态框可能也会用到类似逻辑，虽此处主要为页面提交)
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or \
                  request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'

        if is_ajax:
            # 渲染新卡片 HTML
            # 伪造一个 version_count = 1
            group.version_count = 1 
            html = render_to_string('gallery/components/home_group_card.html', {
                'group': group,
            }, request=request) # 传递 request 确保 tag 渲染正常
            return JsonResponse({
                'status': 'success',
                'html': html,
                'message': f"成功发布！包含 {len(created_image_ids)} 张图片"
            })

        # return redirect('home')

    else:
        # === GET 请求：渲染上传页面 ===
        batch_id = request.GET.get('batch_id')
        temp_files_preview = []
        
        if batch_id:
            temp_dir = get_temp_dir(batch_id)
            if os.path.exists(temp_dir):
                try:
                    file_names = os.listdir(temp_dir)
                    for name in file_names:
                        full_path = os.path.join(temp_dir, name)
                        if os.path.isfile(full_path):
                            temp_files_preview.append({
                                'name': name, 
                                'url': f"{settings.MEDIA_URL}temp_uploads/{batch_id}/{name}",
                                'size': os.path.getsize(full_path) 
                            })
                except Exception as e:
                    print(f"Error reading temp dir: {e}")
        
        form = PromptGroupForm()
        existing_titles = PromptGroup.objects.values_list('title', flat=True).distinct().order_by('title')
        all_models = AIModel.objects.all()

        # 【核心修正】将 Python 列表转为 JSON 字符串
        # 否则模板中使用 {{ temp_files }} 输出的是单引号的 Python 格式，JS 无法解析
        temp_files_json = json.dumps(temp_files_preview)

        return render(request, 'gallery/upload.html', {
            'form': form,
            'existing_titles': existing_titles,
            'all_models': all_models,
            'batch_id': batch_id,
            'temp_files': temp_files_json  # 传过去 JSON 字符串
        })


def check_duplicates(request):
    if request.method == 'POST':
        files = request.FILES.getlist('images')
        results = []
        has_duplicate = False
        
        batch_id = str(uuid.uuid4())
        temp_dir = get_temp_dir(batch_id)
        os.makedirs(temp_dir, exist_ok=True)

        for f in files:
            f_hash = calculate_file_hash(f)
            
            f.seek(0)
            safe_name = os.path.basename(f.name)
            file_path = os.path.join(temp_dir, safe_name)
            
            with open(file_path, 'wb+') as destination:
                for chunk in f.chunks():
                    destination.write(chunk)
            
            existing = ImageItem.objects.filter(image_hash=f_hash).select_related('group').first()
            
            if existing:
                has_duplicate = True
                results.append({
                    'status': 'duplicate',
                    'filename': safe_name,
                    'existing_group_title': existing.group.title,
                    'existing_group_id': existing.group.id,
                    'thumbnail_url': existing.thumbnail.url if existing.thumbnail else existing.image.url
                })
            else:
                results.append({
                    'status': 'pass',
                    'filename': safe_name,
                    'thumbnail_url': f"{settings.MEDIA_URL}temp_uploads/{batch_id}/{safe_name}" 
                })
        
        return JsonResponse({
            'status': 'success', 
            'results': results,
            'has_duplicate': has_duplicate,
            'batch_id': batch_id
        })
    
    return JsonResponse({'status': 'error', 'message': '仅支持 POST 请求'})

@require_POST
def toggle_like_group(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    group.is_liked = not group.is_liked
    group.save()
    return JsonResponse({'status': 'success', 'is_liked': group.is_liked})

@require_POST
def toggle_like_image(request, pk):
    image = get_object_or_404(ImageItem, pk=pk)
    image.is_liked = not image.is_liked
    image.save()
    return JsonResponse({'status': 'success', 'is_liked': image.is_liked})

def add_images_to_group(request, pk):
    """【修复版】添加生成图：支持 AJAX JSON 返回"""
    group = get_object_or_404(PromptGroup, pk=pk)
    
    if request.method == 'POST':
        # 检测是否为 AJAX 请求（兼容旧版 Django 和各类代理）
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or \
                  request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
                  
        try:
            files = request.FILES.getlist('new_images')
            duplicates = []
            uploaded_count = 0
            created_ids = []

            if files:
                for f in files:
                    file_hash = calculate_file_hash(f)
                    existing_img = ImageItem.objects.filter(group=group, image_hash=file_hash).first()
                    
                    if existing_img:
                        duplicates.append({
                            'name': f.name,
                            'existing_group_title': existing_img.group.title,
                            'existing_url': existing_img.thumbnail.url if existing_img.thumbnail else existing_img.image.url
                        })
                    else:
                        img_item = ImageItem(group=group, image=f)
                        img_item.image_hash = file_hash
                        img_item.save()
                        created_ids.append(img_item.id)
                        uploaded_count += 1
            
            # 触发后台处理
            if created_ids:
                trigger_background_processing(created_ids)

            # === [关键修复] AJAX 请求返回 JSON，不跳转 ===
            if is_ajax:
                # 获取新上传的图片，按 ID 正序排列（前端 unshift 时正好变成倒序）
                new_images = ImageItem.objects.filter(id__in=created_ids).order_by('id')
                
                new_images_data = []
                html_list = []
                
                for img in new_images:
                    # 1. 构造前端需要的 JSON 数据
                    new_images_data.append({
                        'id': img.pk,
                        'url': img.image.url,
                        'isLiked': img.is_liked
                    })
                    
                    # 2. 渲染 HTML 卡片
                    # 注意：detail_image_card.html 必须使用 img.pk 而不是 index
                    html = render_to_string('gallery/components/detail_image_card.html', {
                        'img': img, 
                        # 'index': ... 不需要了，改用 ID
                    }, request=request)
                    html_list.append(html)

                return JsonResponse({
                    'status': 'success' if not duplicates else 'warning',
                    'uploaded_count': uploaded_count,
                    'duplicates': duplicates,
                    'new_images_html': html_list,
                    'new_images_data': new_images_data, # 返回数据供前端更新
                    'type': 'gen'
                })
            
            # 普通表单提交的回退处理
            if duplicates:
                messages.warning(request, f"成功添加 {uploaded_count} 张，忽略 {len(duplicates)} 张重复图片")
            else:
                messages.success(request, f"成功添加 {uploaded_count} 张图片")
        
        except Exception as e:
            # 如果是 AJAX 请求发生异常，返回 JSON 错误而不是让前端解析 HTML 失败
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
            raise e
            
    return redirect('detail', pk=pk)


def add_references_to_group(request, pk):
    """【修复版】添加参考图：支持 AJAX JSON 返回"""
    group = get_object_or_404(PromptGroup, pk=pk)
    
    if request.method == 'POST':
        # 检测 AJAX
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or \
                  request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'

        try:
            files = request.FILES.getlist('new_references')
            new_refs = []
            if files:
                for f in files:
                    ref = ReferenceItem.objects.create(group=group, image=f)
                    new_refs.append(ref)
            
            # === [关键修复] AJAX 请求返回 JSON，包含新图片的 HTML ===
            if is_ajax:
                html_list = []
                for ref in new_refs:
                    html = render_to_string('gallery/components/detail_reference_item.html', {
                        'ref': ref,
                    }, request=request)
                    html_list.append(html)
                
                return JsonResponse({
                    'status': 'success',
                    'uploaded_count': len(new_refs),
                    'new_references_html': html_list,
                    'type': 'ref'  # 标记类型为参考图
                })
        except Exception as e:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
            raise e

    return redirect('detail', pk=pk)


def delete_group(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    if request.method == 'POST':
        for img in group.images.all():
            if img.image:
                img.image.delete(save=False)
        for ref in group.references.all():
            if ref.image:
                ref.image.delete(save=False)
        group.delete()
        messages.success(request, "已删除该组内容")
        return redirect('home')
    return redirect('detail', pk=pk)


def delete_image(request, pk):
    image_item = get_object_or_404(ImageItem, pk=pk)
    group_pk = image_item.group.pk
    if request.method == 'POST':
        image_item.image.delete(save=False)
        image_item.delete()
    return redirect('detail', pk=group_pk)


def delete_reference(request, pk):
    item = get_object_or_404(ReferenceItem, pk=pk)
    group_pk = item.group.pk
    if request.method == 'POST':
        item.image.delete(save=False)
        item.delete()
    return redirect('detail', pk=group_pk)


@require_POST
def update_group_prompts(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    try:
        data = json.loads(request.body)
        if 'prompt_text' in data:
            group.prompt_text = data['prompt_text']
        if 'prompt_text_zh' in data:
            group.prompt_text_zh = data['prompt_text_zh']
        if 'negative_prompt' in data:
            group.negative_prompt = data['negative_prompt']
        if 'model_info' in data:
            group.model_info = data['model_info']
            
        group.save()
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)


@require_POST
def add_tag_to_group(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    try:
        data = json.loads(request.body)
        tag_name = data.get('tag_name', '').strip()
        if not tag_name:
            return JsonResponse({'status': 'error', 'message': '标签名不能为空'})
        
        tag, created = Tag.objects.get_or_create(name=tag_name)
        group.tags.add(tag)
        
        return JsonResponse({'status': 'success', 'tag_id': tag.id, 'tag_name': tag.name})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})


@require_POST
def remove_tag_from_group(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    try:
        data = json.loads(request.body)
        tag_id = data.get('tag_id')
        tag = get_object_or_404(Tag, pk=tag_id)
        
        group.tags.remove(tag)
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
    
@require_GET
def group_list_api(request):
    """【升级版】提供去重后的列表，并附带组内数量"""
    query = request.GET.get('q', '')
    page_num = request.GET.get('page', 1)
    
    qs = PromptGroup.objects.all()
    
    if query:
        matching_group_ids = qs.filter(
            Q(title__icontains=query) |
            Q(prompt_text__icontains=query) |
            Q(tags__name__icontains=query)
        ).values_list('group_id', flat=True).distinct()
        
        qs = qs.filter(group_id__in=matching_group_ids)
    
    group_stats = qs.values('group_id').annotate(
        max_id=Max('id'),     
        count=Count('id')     
    )
    
    latest_ids = [item['max_id'] for item in group_stats]
    count_map = {item['max_id']: item['count'] for item in group_stats}
    
    final_qs = PromptGroup.objects.filter(id__in=latest_ids).order_by('-id')
    
    paginator = Paginator(final_qs, 20)
    page = paginator.get_page(page_num)
    
    data = []
    for group in page:
        cover_url = ""
        if group.images.exists():
            try:
                cover_url = group.images.first().thumbnail.url
            except:
                pass
        
        data.append({
            'id': group.id,
            'title': group.title,
            'prompt_text': (group.prompt_text[:100] + '...') if group.prompt_text and len(group.prompt_text) > 100 else (group.prompt_text or ''),
            'created_at': group.created_at.strftime('%Y-%m-%d'),
            'cover_url': cover_url,
            'model_info': group.model_info or '',
            'group_id': str(group.group_id),
            'count': count_map.get(group.id, 1) 
        })
        
    return JsonResponse({
        'results': data,
        'has_next': page.has_next(),
        'next_page_number': page.next_page_number() if page.has_next() else None
    })

@require_POST
def merge_groups(request):
    """【升级版】按家族进行合并"""
    try:
        data = json.loads(request.body)
        representative_ids = data.get('group_ids', [])
        
        if len(representative_ids) < 2:
            return JsonResponse({'status': 'error', 'message': '请至少选择两个组进行合并'})
            
        target_reps = PromptGroup.objects.filter(id__in=representative_ids)
        if not target_reps.exists():
            return JsonResponse({'status': 'error', 'message': '找不到选中的组'})
            
        involved_group_ids = target_reps.values_list('group_id', flat=True).distinct()
        
        target_group_id = involved_group_ids[0]
        
        count = PromptGroup.objects.filter(group_id__in=involved_group_ids).update(group_id=target_group_id)
        
        return JsonResponse({
            'status': 'success', 
            'message': f'合并成功！共 {count} 个版本已归为同一系列。'
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
    
# 【新增】解除关联 API
@require_POST
def unlink_group_relation(request, pk):
    """将指定组(pk)从当前系列中移除（赋予新的 group_id）"""
    group = get_object_or_404(PromptGroup, pk=pk)
    # 生成新的 UUID，使其独立
    group.group_id = uuid.uuid4()
    group.save()
    return JsonResponse({'status': 'success'})

# 【新增】添加关联 API
@require_POST
def link_group_relation(request, pk):
    """将目标组(target_id)合并到当前组(pk)的系列中"""
    current_group = get_object_or_404(PromptGroup, pk=pk)
    try:
        data = json.loads(request.body)
        target_id = data.get('target_id')
        target_group = get_object_or_404(PromptGroup, pk=target_id)
        
        # 将目标组的 group_id 更新为当前组的 group_id
        target_group.group_id = current_group.group_id
        target_group.save()
        
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})