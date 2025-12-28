import hashlib
import json
from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db.models import Q, Count, Case, When, IntegerField
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import PromptGroup, ImageItem, Tag, AIModel, ReferenceItem
from .forms import PromptGroupForm
from .ai_utils import generate_image_embedding, search_similar_images

# === 计算上传文件 MD5 的工具函数 ===
def calculate_file_hash(uploaded_file):
    md5 = hashlib.md5()
    for chunk in uploaded_file.chunks():
        md5.update(chunk)
    return md5.hexdigest()

def home(request):
    queryset = PromptGroup.objects.all()
    query = request.GET.get('q')
    filter_type = request.GET.get('filter')

    if filter_type == 'liked':
        queryset = queryset.filter(is_liked=True)

    if query:
        queryset = queryset.filter(
            Q(title__icontains=query) |
            Q(prompt_text__icontains=query) |
            Q(prompt_text_zh__icontains=query) | # 支持搜索中文提示词
            Q(tags__name__icontains=query)
        ).distinct()

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
    next_url = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER') or '/'
    if '/upload/' in next_url:
        next_url = '/'
    existing_titles = PromptGroup.objects.values_list('title', flat=True).distinct().order_by('title')

    if request.method == 'POST':
        form = PromptGroupForm(request.POST, request.FILES)
        if form.is_valid():
            prompt_content = form.cleaned_data.get('prompt_text', '').strip()
            model_obj = form.cleaned_data.get('model_info')
            model_name_str = model_obj.name if model_obj else ""

            is_duplicate = PromptGroup.objects.filter(
                prompt_text=prompt_content, 
                model_info=model_name_str
            ).exists()

            if is_duplicate:
                error_msg = f"重复提交拦截：该提示词与模型 '{model_name_str}' 的组合已存在！"
                if not model_name_str: error_msg = "重复提交拦截：该提示词已存在！"
                form.add_error(None, error_msg)
                return render(request, 'gallery/upload.html', {
                    'form': form, 'next_url': next_url, 'existing_titles': existing_titles 
                })

            group = form.save(commit=False)
            selected_model_obj = form.cleaned_data.get('model_info')
            if selected_model_obj:
                group.model_info = selected_model_obj.name
            group.save()
            form.save_m2m()

            if selected_model_obj:
                model_tag, created = Tag.objects.get_or_create(name=selected_model_obj.name)
                group.tags.add(model_tag)
            
            files = request.FILES.getlist('upload_images')
            for f in files:
                img_item = ImageItem(group=group, image=f)
                img_item.save()
                try:
                    vec = generate_image_embedding(img_item.image.path)
                    if vec:
                        img_item.feature_vector = vec
                        img_item.save()
                except Exception as e:
                    print(f"向量生成失败: {e}")

            ref_files = request.FILES.getlist('upload_references')
            for f in ref_files:
                ReferenceItem.objects.create(group=group, image=f)
            
            return redirect(next_url)
    else:
        form = PromptGroupForm()
    
    return render(request, 'gallery/upload.html', {
        'form': form,
        'next_url': next_url,
        'existing_titles': existing_titles 
    })

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

        if files:
            for f in files:
                file_hash = calculate_file_hash(f)
                existing_img = ImageItem.objects.filter(group=group, image_hash=file_hash).first()
                
                if existing_img:
                    duplicates.append({
                        'name': f.name,
                        'existing_url': existing_img.thumbnail.url if existing_img.thumbnail else existing_img.image.url,
                        'existing_group_title': existing_img.group.title,
                        'existing_group_id': existing_img.group.id
                    })
                else:
                    img_item = ImageItem(group=group, image=f)
                    img_item.image_hash = file_hash
                    img_item.save()
                    uploaded_count += 1
                    try:
                        vec = generate_image_embedding(img_item.image.path)
                        if vec:
                            img_item.feature_vector = vec
                            img_item.save()
                    except: pass
        
        if duplicates:
            return JsonResponse({
                'status': 'warning',
                'message': f'成功上传 {uploaded_count} 张，拦截 {len(duplicates)} 张重复图片',
                'duplicates': duplicates,
                'uploaded_count': uploaded_count
            })
        else:
            return JsonResponse({
                'status': 'success',
                'message': f'成功添加 {uploaded_count} 张图片',
                'uploaded_count': uploaded_count
            })
            
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
        group.delete()
        return redirect('home')
    return redirect('detail', pk=pk)

def delete_image(request, pk):
    image_item = get_object_or_404(ImageItem, pk=pk)
    group_pk = image_item.group.pk
    if request.method == 'POST':
        image_item.delete()
    return redirect('detail', pk=group_pk)

def delete_reference(request, pk):
    item = get_object_or_404(ReferenceItem, pk=pk)
    group_pk = item.group.pk
    if request.method == 'POST':
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
            
        # === 新增：处理模型信息更新 ===
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