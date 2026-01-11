import os
import uuid
import json
from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Q, Count, Case, When, IntegerField
from django.contrib import messages
from django.core.paginator import Paginator
from django.views.decorators.http import require_GET,require_POST
from django.core.cache import cache
from django.db.models import Q, Count, Case, When, IntegerField, Max  # 【修改】添加 Max
from .models import ImageItem, PromptGroup, Tag, AIModel, ReferenceItem
from .forms import PromptGroupForm
from .ai_utils import search_similar_images
from django.db.models import Max, Count

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

# ==========================================
# 视图函数
# ==========================================

def home(request):
    queryset = PromptGroup.objects.all()
    query = request.GET.get('q')
    filter_type = request.GET.get('filter')
    # 获取 URL 中的 search_id (用于恢复以图搜图结果)
    search_id = request.GET.get('search_id')

    # === 1. 处理以图搜图提交 (POST) -> 转为 GET ===
    if request.method == 'POST' and request.FILES.get('search_image'):
        try:
            search_file = request.FILES['search_image']
            
            # 搜索全库图片
            similar_images = search_similar_images(search_file, ImageItem.objects.all(), top_k=50)
            
            if not similar_images:
                messages.info(request, "未找到相似图片")
                return redirect('home')
            
            # 生成唯一ID，将结果存入缓存
            search_uuid = str(uuid.uuid4())
            
            # 仅缓存 ID 和 分数
            cache_data = [
                {'id': img.id, 'score': getattr(img, 'similarity_score', 0)} 
                for img in similar_images
            ]
            
            # 存入 Cache (有效期 1 小时)
            cache_key = f"home_search_{search_uuid}"
            cache.set(cache_key, cache_data, 3600)
            
            # 重定向到首页，带上 search_id
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
            # 从缓存恢复数据
            ids = [item['id'] for item in cached_data]
            id_score_map = {item['id']: item['score'] for item in cached_data}
            
            # 使用 filter 代替 in_bulk
            images_list = list(ImageItem.objects.filter(id__in=ids))
            objects_dict = {img.id: img for img in images_list}
            
            # 按缓存的顺序重组列表
            restored_images = []
            for img_id in ids:
                if img_id in objects_dict:
                    obj = objects_dict[img_id]
                    obj.similarity_score = id_score_map.get(img_id, 0)
                    restored_images.append(obj)
            
            # 【新增】以图搜图结果页也需要标签栏
            tags_bar = get_tags_bar_data()

            if restored_images:
                return render(request, 'gallery/liked_images.html', {
                    'page_obj': restored_images,
                    'search_query': '全库以图搜图结果',
                    'search_mode': 'image',
                    'is_home_search': True,
                    'current_search_id': search_id,
                    'tags_bar': tags_bar  # 传递标签数据
                })
        else:
            messages.warning(request, "搜索结果已过期，请重新搜索")

    # === 常规文本搜索 ===
    if query:
        # 【搜索模式】：显示所有匹配结果，不去重，方便找回历史版本
        queryset = queryset.filter(
            Q(title__icontains=query) |
            Q(prompt_text__icontains=query) |
            Q(prompt_text_zh__icontains=query) |
            Q(tags__name__icontains=query)
        ).distinct()
    else:
        # 【默认浏览模式】：启用“家族折叠”，只显示每个系列最新的一个
        # 1. 按 group_id 分组，找到每组最大的 ID (即最新创建的)
        latest_ids_in_group = PromptGroup.objects.values('group_id').annotate(
            max_id=Max('id')
        ).values_list('max_id', flat=True)

        # 2. 过滤 queryset，只保留这些 ID
        queryset = queryset.filter(id__in=latest_ids_in_group)
    
    if filter_type == 'liked':
        queryset = queryset.filter(is_liked=True)

    # 获取标签栏数据
    tags_bar = get_tags_bar_data()

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
    search_id = request.GET.get('search_id') 
    
    # === 1. 图墙以图搜图提交 ===
    if request.method == 'POST' and request.FILES.get('image_query'):
        try:
            uploaded_file = request.FILES['image_query']
            results = search_similar_images(uploaded_file, queryset) 
            
            search_uuid = str(uuid.uuid4())
            cache_data = [
                {'id': img.id, 'score': getattr(img, 'similarity_score', 0)} 
                for img in results
            ]
            
            cache_key = f"liked_search_{search_uuid}"
            cache.set(cache_key, cache_data, 3600)
            
            # 【修复】：路径从 /liked/ 改为 /liked-images/ 以匹配 urls.py
            return redirect(f"/liked-images/?search_id={search_uuid}")
            
        except Exception as e:
            messages.error(request, "搜索失败")
            return redirect('liked_images_gallery')

    # === 2. 图墙以图搜图结果 ===
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
    
    # 【新增】获取标签栏数据
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
        'tags_bar': tags_bar # 传递标签数据
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
    
    # 详情页原有的所有标签（用于自动补全）
    all_tags = Tag.objects.annotate(
        usage_count=Count('promptgroup')
    ).order_by('-usage_count', 'name')[:500]

    # 【修改】查找同系列的其他版本 (Group ID 相同，但 ID 不同)
    siblings = PromptGroup.objects.filter(
        group_id=group.group_id
    ).exclude(pk=group.pk).order_by('-created_at')

    related_groups = PromptGroup.objects.filter(
        tags__in=group.tags.all()
    ).exclude(pk=pk).distinct()[:4]
    
    # 【新增】获取侧边栏标签数据
    tags_bar = get_tags_bar_data()

    return render(request, 'gallery/detail.html', {
        'group': group,
        'sorted_tags': tags_list,
        'all_tags': all_tags,
        'siblings': siblings,      # 【新增】传递给模板
        'related_groups': related_groups,
        'tags_bar': tags_bar, # 传递标签数据
        'search_query': request.GET.get('q') # 传递搜索词以便高亮标签
    })


def upload(request):
    if request.method == 'POST':
        # 判断是否确认提交 (表单中有 hidden input name="confirmed" value="1")
        # 如果是直接上传，该字段也存在。
        
        prompt_text = request.POST.get('prompt_text', '')
        prompt_text_zh = request.POST.get('prompt_text_zh', '')
        negative_prompt = request.POST.get('negative_prompt', '')
        title = request.POST.get('title', '') or '未命名组'
        model_id = request.POST.get('model_info')
        
        # 1. 处理模型
        model_name_str = ""
        if model_id:
            try:
                model_instance = AIModel.objects.get(id=model_id)
                model_name_str = model_instance.name
            except AIModel.DoesNotExist:
                pass

        # 2. 创建 PromptGroup
        group = PromptGroup.objects.create(
            title=title,
            prompt_text=prompt_text,
            prompt_text_zh=prompt_text_zh,
            negative_prompt=negative_prompt,
            model_info=model_name_str,
        )
        
        # 3. 处理标签 (支持 checkbox 选中的 ID 和 可能的文本输入)
        selected_tags = request.POST.getlist('tags')
        
        for tag_val in selected_tags:
            tag_val = tag_val.strip()
            if not tag_val: continue
            
            # 如果是纯数字，尝试按 ID 查找；否则按名称查找
            if tag_val.isdigit():
                try:
                    group.tags.add(Tag.objects.get(id=int(tag_val)))
                except Tag.DoesNotExist:
                    pass
            else:
                tag, _ = Tag.objects.get_or_create(name=tag_val)
                group.tags.add(tag)
        
        # 自动将模型也作为一个标签
        if model_name_str:
            m_tag, _ = Tag.objects.get_or_create(name=model_name_str)
            group.tags.add(m_tag)

        created_image_ids = []

        # 4. 图片处理逻辑 (关键修复)
        # ----------------------------------------------------------
        # 场景 A: 本地直接上传的文件 (存在于 request.FILES 中)
        direct_files = request.FILES.getlist('upload_images')
        for f in direct_files:
            img_item = ImageItem(group=group, image=f)
            img_item.save() # 保存触发哈希计算
            created_image_ids.append(img_item.id)

        # 场景 B: 经过查重的服务器暂存文件 (存在于 temp_uploads 目录中)
        batch_id = request.POST.get('batch_id')
        server_file_names = request.POST.getlist('selected_files')
        
        if batch_id and server_file_names:
            # 移动暂存文件并创建记录
            temp_ids = confirm_upload_images(batch_id, server_file_names, group)
            created_image_ids.extend(temp_ids)
            
        # 场景 C: 参考图直接上传
        ref_files = request.FILES.getlist('upload_references')
        for rf in ref_files:
            ReferenceItem.objects.create(group=group, image=rf)
        # ----------------------------------------------------------

        if not created_image_ids:
            messages.warning(request, "虽然发布了作品，但未上传任何生成图。")
        else:
            trigger_background_processing(created_image_ids)
            messages.success(request, f"成功发布！包含 {len(created_image_ids)} 张图片，系统正在后台处理索引。")
            
        return redirect('home')

    else:
        # GET 请求：渲染上传页面
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
                except Exception:
                    pass
        
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
                        'existing_group_title': existing_img.group.title,
                        'existing_url': existing_img.thumbnail.url if existing_img.thumbnail else existing_img.image.url
                    })
                else:
                    img_item = ImageItem(group=group, image=f)
                    img_item.image_hash = file_hash
                    img_item.save()
                    created_ids.append(img_item.id)
                    uploaded_count += 1
        
        trigger_background_processing(created_ids)

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            if duplicates:
                return JsonResponse({
                    'status': 'warning',
                    'uploaded_count': uploaded_count,
                    'duplicates': duplicates
                })
            else:
                messages.success(request, f"成功添加 {uploaded_count} 张图片")
                return JsonResponse({'status': 'success', 'uploaded_count': uploaded_count})

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
    
@require_GET
def group_list_api(request):
    """【升级版】提供去重后的列表，并附带组内数量"""
    query = request.GET.get('q', '')
    page_num = request.GET.get('page', 1)
    
    # 1. 基础查询
    qs = PromptGroup.objects.all()
    
    # 2. 搜索过滤：先找出符合搜索条件的 group_id
    # 如果用户搜“红衣服”，我们要把包含“红衣服”的那个家族找出来
    if query:
        matching_group_ids = qs.filter(
            Q(title__icontains=query) |
            Q(prompt_text__icontains=query) |
            Q(tags__name__icontains=query)
        ).values_list('group_id', flat=True).distinct()
        
        # 锁定范围到这些家族
        qs = qs.filter(group_id__in=matching_group_ids)
    
    # 3. 聚合去重：按 group_id 分组，找出【最新ID】和【成员数量】
    # values('group_id') 相当于 SQL 的 GROUP BY group_id
    group_stats = qs.values('group_id').annotate(
        max_id=Max('id'),     # 取该组最新的一个 ID 作为代表
        count=Count('id')     # 统计该组有多少个
    )
    
    # 4. 构建映射表与ID列表
    latest_ids = [item['max_id'] for item in group_stats]
    count_map = {item['max_id']: item['count'] for item in group_stats}
    
    # 5. 查询实体对象 (只查询代表)
    # order_by('-id') 确保刚创建/刚修改的排在最前
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
            'count': count_map.get(group.id, 1)  # 【新增】返回该组的数量
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
        # 这里接收的是用户选中的“代表ID”
        representative_ids = data.get('group_ids', [])
        
        if len(representative_ids) < 2:
            return JsonResponse({'status': 'error', 'message': '请至少选择两个组进行合并'})
            
        # 1. 根据代表ID，反向查出它们所属的 group_id (家族ID)
        # 例如：选中了 ID=100(属于家族A) 和 ID=200(属于家族B)
        target_reps = PromptGroup.objects.filter(id__in=representative_ids)
        if not target_reps.exists():
            return JsonResponse({'status': 'error', 'message': '找不到选中的组'})
            
        involved_group_ids = target_reps.values_list('group_id', flat=True).distinct()
        
        # 2. 确定合并目标 (使用第一个被选中代表的家族ID作为新家族ID)
        target_group_id = involved_group_ids[0]
        
        # 3. 【核心修改】将所有涉及到的家族成员全部合并
        # update PromptGroup set group_id = target where group_id IN (家族A, 家族B)
        # 这样家族A和家族B的所有成员（不管有没有在列表里显示）都会被合并
        count = PromptGroup.objects.filter(group_id__in=involved_group_ids).update(group_id=target_group_id)
        
        return JsonResponse({
            'status': 'success', 
            'message': f'合并成功！共 {count} 个版本已归为同一系列。'
        })
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})