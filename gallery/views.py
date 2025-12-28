import hashlib
import json
import os
import shutil
import uuid
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db.models import Q, Count, Case, When, IntegerField
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from .models import PromptGroup, ImageItem, Tag, AIModel, ReferenceItem
from .forms import PromptGroupForm
from .ai_utils import generate_image_embedding, search_similar_images

def calculate_file_hash(file_obj):
    """
    计算文件的 MD5 哈希值
    """
    md5 = hashlib.md5()
    for chunk in file_obj.chunks():
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
    """
    发布/上传页面视图：
    支持处理来自查重工具的临时文件 (batch_id)
    """
    # 处理登录后的跳转逻辑
    next_url = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER') or '/'
    if '/upload/' in next_url: next_url = '/'
    
    # 获取已有的标题列表（用于前端自动补全）
    existing_titles = PromptGroup.objects.values_list('title', flat=True).distinct().order_by('title')

    # === 处理 batch_id (来自查重跳转) ===
    batch_id = request.POST.get('batch_id') or request.GET.get('batch_id')
    temp_files_preview = [] # 用于在模板显示的预览信息
    
    # 尝试加载临时目录中的文件信息
    if batch_id:
        temp_dir = get_temp_dir(batch_id)
        if os.path.exists(temp_dir):
            file_names = os.listdir(temp_dir)
            # 生成预览数据供前端展示
            temp_files_preview = [
                {
                    'name': name, 
                    # 注意：这里假设你的 MEDIA_URL 设置正确
                    'url': f"{settings.MEDIA_URL}temp_uploads/{batch_id}/{name}"
                } 
                for name in file_names
            ]

    if request.method == 'POST':
        # 复制 request.FILES 使其可修改 (MultiValueDict)
        files_data = request.FILES.copy()
        
        # === 核心逻辑：合并临时文件到表单数据中 ===
        if batch_id:
            temp_dir = get_temp_dir(batch_id)
            if os.path.exists(temp_dir):
                for name in os.listdir(temp_dir):
                    path = os.path.join(temp_dir, name)
                    # 读取临时文件并封装成 Django 可处理的 SimpleUploadedFile
                    with open(path, 'rb') as f:
                        file_content = f.read()
                        # 创建虚拟上传文件对象 (默认 mime type 为 image/jpeg，Django 会自动校验)
                        s_file = SimpleUploadedFile(name, file_content, content_type="image/jpeg")
                        # 将文件追加到 upload_images 字段中
                        files_data.appendlist('upload_images', s_file)

        # 实例化表单，传入合并后的文件数据
        form = PromptGroupForm(request.POST, files_data)
        
        if form.is_valid():
            # 1. 保存 PromptGroup 基本信息
            group = form.save(commit=False)
            
            # 处理模型信息
            model_obj = form.cleaned_data.get('model_info')
            if model_obj:
                group.model_info = model_obj.name
                # 自动将模型名添加为标签
                model_tag, _ = Tag.objects.get_or_create(name=model_obj.name)
            
            group.save()
            form.save_m2m() # 保存多对多关系 (如 tags)
            
            if model_obj:
                group.tags.add(model_tag)

            # 2. 保存图片 (ImageItem)
            # 此时 cleaned_data['upload_images'] 包含了用户新上传的和 batch_id 带来的文件
            files = form.cleaned_data.get('upload_images')
            if files:
                for f in files:
                    # 保存图片对象
                    img_item = ImageItem(group=group, image=f)
                    
                    # 计算哈希 (确保入库时也有哈希值)
                    # 注意：如果 f 是 SimpleUploadedFile，chunks() 也能正常工作
                    if not img_item.image_hash:
                         img_item.image_hash = calculate_file_hash(f)
                    
                    img_item.save()

                    # 触发向量生成 (如果有此逻辑)
                    # try:
                    #     get_embedding(img_item.pk)
                    # except Exception as e:
                    #     print(f"Embedding error: {e}")
            
            # 3. 保存参考图 (如果有)
            ref_files = form.cleaned_data.get('upload_references')
            if ref_files:
                for rf in ref_files:
                    # 假设你有 ReferenceItem 模型，或者用类似逻辑处理
                    pass 
                    # 你的项目中似乎是在 PromptGroup 上处理或者有 ReferenceItem，请根据实际情况保留原逻辑
            
            # 4. === 清理临时文件 ===
            # 如果使用了 batch_id，数据已保存到正式目录，删除临时目录
            if batch_id:
                temp_dir = get_temp_dir(batch_id)
                if os.path.exists(temp_dir) and os.path.isdir(temp_dir):
                    try:
                        shutil.rmtree(temp_dir)
                    except OSError as e:
                        print(f"Error deleting temp dir: {e}")

            return redirect(next_url)
    else:
        form = PromptGroupForm()
    
    return render(request, 'gallery/upload.html', {
        'form': form,
        'next_url': next_url,
        'existing_titles': existing_titles,
        'batch_id': batch_id,       # 传递给模板：用于标记当前是否处于带图发布状态
        'temp_files': temp_files_preview # 传递给模板：用于展示预览图
    })

def get_temp_dir(batch_id):
    """
    获取临时文件存储路径
    """
    return os.path.join(settings.MEDIA_ROOT, 'temp_uploads', batch_id)

def check_duplicates(request):
    """
    全库查重接口：
    1. 计算上传文件的哈希值
    2. 比对数据库是否存在重复
    3. 将文件暂存到临时目录，返回 batch_id 供发布页使用
    """
    if request.method == 'POST':
        files = request.FILES.getlist('images')
        results = []
        has_duplicate = False
        
        # 1. 生成批次 ID 并创建临时目录
        batch_id = str(uuid.uuid4())
        temp_dir = get_temp_dir(batch_id)
        os.makedirs(temp_dir, exist_ok=True)

        for f in files:
            # 计算哈希
            f_hash = calculate_file_hash(f)
            
            # 2. 暂存文件到磁盘 (关键步骤：为了传给发布页)
            # 必须重置文件指针，因为 calculate_file_hash 读取了文件
            f.seek(0)
            file_path = os.path.join(temp_dir, f.name)
            
            # 以二进制写入模式保存临时文件
            with open(file_path, 'wb+') as destination:
                for chunk in f.chunks():
                    destination.write(chunk)
            
            # 3. 查重比对 (查找全库，不仅是当前用户)
            existing = ImageItem.objects.filter(image_hash=f_hash).select_related('group').first()
            
            if existing:
                has_duplicate = True
                results.append({
                    'status': 'duplicate',
                    'filename': f.name,
                    'existing_group_title': existing.group.title,
                    'existing_group_id': existing.group.id,
                    # 优先使用缩略图，如果没有则用原图
                    'thumbnail_url': existing.thumbnail.url if existing.thumbnail else existing.image.url
                })
            else:
                results.append({
                    'status': 'pass',
                    'filename': f.name
                })
        
        return JsonResponse({
            'status': 'success', 
            'results': results,
            'has_duplicate': has_duplicate,
            'batch_id': batch_id  # 返回批次ID给前端
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