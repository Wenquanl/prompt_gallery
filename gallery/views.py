import os
import uuid
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Q, Count, Case, When, IntegerField
from django.contrib import messages
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST

from .models import ImageItem, PromptGroup, Tag, AIModel, ReferenceItem
from .forms import PromptGroupForm
from .ai_utils import search_similar_images

# === 引入 Service 层 ===
from .services import (
    get_temp_dir, 
    calculate_file_hash, 
    trigger_background_processing,
    confirm_upload_images  # 新增的安全处理函数
)

# ==========================================
# 视图函数
# ==========================================

def home(request):
    queryset = PromptGroup.objects.all()
    query = request.GET.get('q')
    filter_type = request.GET.get('filter')

    if request.method == 'POST' and request.FILES.get('search_image'):
        try:
            search_file = request.FILES['search_image']
            similar_items = search_similar_images(search_file, ImageItem.objects.all(), top_k=50)
            
            if not similar_items:
                messages.info(request, "未找到相似图片")
            else:
                group_ids = []
                seen = set()
                for item in similar_items:
                    if item.group_id not in seen:
                        group_ids.append(item.group_id)
                        seen.add(item.group_id)
                
                queryset = queryset.filter(id__in=group_ids)
                
        except Exception as e:
            print(f"Search error: {e}")
            messages.error(request, "搜索过程中发生错误")

    if query:
        queryset = queryset.filter(
            Q(title__icontains=query) |
            Q(prompt_text__icontains=query) |
            Q(prompt_text_zh__icontains=query) |
            Q(tags__name__icontains=query)
        ).distinct()
    
    if filter_type == 'liked':
        queryset = queryset.filter(is_liked=True)

    ai_model_names = list(AIModel.objects.values_list('name', flat=True))
    tags_bar = Tag.objects.filter(promptgroup__isnull=False).distinct().annotate(
        use_count=Count('promptgroup'),
        is_model=Case(
            When(name__in=ai_model_names, then=1),
            default=2,
            output_field=IntegerField(),
        )
    ).order_by('is_model', '-use_count')

    paginator = Paginator(queryset, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'gallery/home.html', {
        'page_obj': page_obj,
        'search_query': query,
        'current_filter': filter_type,
        'tags_bar': tags_bar
    })


def liked_images_gallery(request):
    queryset = ImageItem.objects.filter(is_liked=True).order_by('-id')
    search_mode = 'text'
    query_text = request.GET.get('q')
    
    if request.method == 'POST' and request.FILES.get('image_query'):
        uploaded_file = request.FILES['image_query']
        results = search_similar_images(uploaded_file, queryset)
        queryset = results 
        search_mode = 'image'
        query_text = "按图片搜索结果"
    elif query_text:
        queryset = queryset.filter(
            Q(group__title__icontains=query_text) |
            Q(group__prompt_text__icontains=query_text) |
            Q(group__tags__name__icontains=query_text)
        ).distinct()

    paginator = Paginator(queryset, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'gallery/liked_images.html', {
        'page_obj': page_obj,
        'search_query': query_text,
        'search_mode': search_mode
    })


def detail(request, pk):
    group = get_object_or_404(
        PromptGroup.objects.prefetch_related('tags', 'images', 'references'), 
        pk=pk
    )
    
    tags_list = list(group.tags.all())
    model_name = group.model_info
    if model_name:
        tags_list.sort(key=lambda t: 0 if t.name == model_name else 1)
    
    all_tags = Tag.objects.annotate(
        usage_count=Count('promptgroup')
    ).order_by('-usage_count', 'name')[:500]

    related_groups = PromptGroup.objects.filter(
        tags__in=group.tags.all()
    ).exclude(pk=pk).distinct()[:4]

    return render(request, 'gallery/detail.html', {
        'group': group,
        'sorted_tags': tags_list,
        'all_tags': all_tags,
        'related_groups': related_groups
    })


def upload(request):
    # 如果包含 confirmed 字段，说明是确认发布
    if request.method == 'POST' and 'confirmed' in request.POST:
        batch_id = request.POST.get('batch_id')
        if not batch_id:
            return redirect('upload')
        
        # 1. 创建 PromptGroup
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
        
        tags_str = request.POST.get('tags', '')
        if tags_str:
            tag_names = [t.strip() for t in tags_str.split(',') if t.strip()]
            for name in tag_names:
                tag, _ = Tag.objects.get_or_create(name=name)
                group.tags.add(tag)
        
        if model_name_str:
            m_tag, _ = Tag.objects.get_or_create(name=model_name_str)
            group.tags.add(m_tag)

        # 2. 处理图片文件 (使用 service 层的安全函数)
        # 获取前端确认要提交的文件名列表
        file_names = request.POST.getlist('selected_files')
        
        # 调用安全处理函数：移动文件、创建记录、清理临时目录
        created_image_ids = confirm_upload_images(batch_id, file_names, group)

        if not created_image_ids:
            messages.warning(request, "未找到有效的图片文件，或上传会话已过期。")
        else:
            # 3. 启动后台处理
            trigger_background_processing(created_image_ids)
            messages.success(request, f"成功发布！系统正在后台处理索引。")
            
        return redirect('home')

    else:
        # 常规上传页面渲染
        batch_id = request.GET.get('batch_id')
        temp_files_preview = []
        
        if batch_id:
            # 获取目录时会进行 ID 校验
            temp_dir = get_temp_dir(batch_id)
            if os.path.exists(temp_dir):
                file_names = os.listdir(temp_dir)
                temp_files_preview = [
                    {
                        'name': name, 
                        'url': f"{settings.MEDIA_URL}temp_uploads/{batch_id}/{name}"
                    } 
                    for name in file_names
                ]
        
        form = PromptGroupForm()
        existing_titles = PromptGroup.objects.values_list('title', flat=True).distinct().order_by('title')
        all_models = AIModel.objects.all()

        return render(request, 'gallery/upload.html', {
            'form': form,
            'existing_titles': existing_titles,
            'all_models': all_models,
            'batch_id': batch_id,
            'temp_files': temp_files_preview
        })


def check_duplicates(request):
    """
    全库查重接口
    """
    if request.method == 'POST':
        files = request.FILES.getlist('images')
        results = []
        has_duplicate = False
        
        batch_id = str(uuid.uuid4())
        temp_dir = get_temp_dir(batch_id)
        os.makedirs(temp_dir, exist_ok=True)

        for f in files:
            f_hash = calculate_file_hash(f)
            
            # 暂存文件
            f.seek(0)
            # 使用 os.path.basename 确保文件名安全
            safe_name = os.path.basename(f.name)
            file_path = os.path.join(temp_dir, safe_name)
            
            with open(file_path, 'wb+') as destination:
                for chunk in f.chunks():
                    destination.write(chunk)
            
            # 查重比对
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
    group = get_object_or_404(PromptGroup, pk=pk)
    
    if request.method == 'POST':
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
                        'existing_group_title': existing_img.group.title
                    })
                else:
                    img_item = ImageItem(group=group, image=f)
                    img_item.image_hash = file_hash
                    img_item.save()
                    created_ids.append(img_item.id)
                    uploaded_count += 1
        
        trigger_background_processing(created_ids)

        if duplicates:
            messages.warning(request, f"成功添加 {uploaded_count} 张，忽略 {len(duplicates)} 张重复图片")
        else:
            messages.success(request, f"成功添加 {uploaded_count} 张图片")
            
    return redirect('detail', pk=pk)


def add_references_to_group(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    if request.method == 'POST':
        files = request.FILES.getlist('new_references')
        if files:
            for f in files:
                ReferenceItem.objects.create(group=group, image=f)
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