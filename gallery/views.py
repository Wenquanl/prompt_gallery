from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import PromptGroup, ImageItem, Tag, AIModel, ReferenceItem
from .forms import PromptGroupForm
# 引入 AI 工具
from .ai_utils import generate_image_embedding, search_similar_images

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
            Q(tags__name__icontains=query)
        ).distinct()

    paginator = Paginator(queryset, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    return render(request, 'gallery/home.html', {
        'page_obj': page_obj,
        'search_query': query,
        'current_filter': filter_type
    })

def liked_images_gallery(request):
    # 基础查询：所有喜欢的图片
    queryset = ImageItem.objects.filter(is_liked=True).order_by('-id')
    
    search_mode = 'text' # text 或 image
    query_text = request.GET.get('q')
    
    # 1. 处理以图搜图 (POST上传)
    if request.method == 'POST' and request.FILES.get('image_query'):
        uploaded_file = request.FILES['image_query']
        # 使用 AI 搜索，返回的是已经排好序且带分数的 list
        results = search_similar_images(uploaded_file, queryset)
        
        # 结果已经是 list，不能再用 .filter，直接分页
        queryset = results 
        search_mode = 'image'
        query_text = "按图片搜索结果"

    # 2. 处理文本搜索
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
    group = get_object_or_404(PromptGroup, pk=pk)
    tags_list = list(group.tags.all())
    model_name = group.model_info
    if model_name:
        tags_list.sort(key=lambda t: 0 if t.name == model_name else 1)
    
    related_groups = PromptGroup.objects.filter(
        tags__in=group.tags.all()
    ).exclude(pk=pk).distinct()[:4]

    return render(request, 'gallery/detail.html', {
        'group': group,
        'sorted_tags': tags_list,
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
                img_item = ImageItem.objects.create(group=group, image=f)
                # 【关键】上传时自动生成向量
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
        if files:
            for f in files:
                img_item = ImageItem.objects.create(group=group, image=f)
                # 【关键】追加图片时也生成向量
                try:
                    vec = generate_image_embedding(img_item.image.path)
                    if vec:
                        img_item.feature_vector = vec
                        img_item.save()
                except: pass
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