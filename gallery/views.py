import os
import time
import difflib
import uuid
import json
import re
import shutil
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Q, Count, Case, When, IntegerField, Max, Prefetch
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.views.decorators.http import require_GET, require_POST
from django.core.cache import cache
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
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

def generate_diff_html(base_text, compare_text):
    """
    比较 compare_text (其他版本) 相对于 base_text (当前版本) 的差异。
    只返回差异部分的 HTML。
    """
    if base_text is None: base_text = ""
    if compare_text is None: compare_text = ""
    
    def parse_tags_to_dict(text):
        parts = re.split(r'[,\uff0c\n]+', text)
        return {p.strip().lower(): p.strip() for p in parts if p.strip()}

    base_map = parse_tags_to_dict(base_text)
    comp_map = parse_tags_to_dict(compare_text)
    
    base_keys = set(base_map.keys())
    comp_keys = set(comp_map.keys())
    
    added_keys = comp_keys - base_keys
    removed_keys = base_keys - comp_keys
    
    if not added_keys and not removed_keys:
        return '<span class="no-diff">无提示词差异</span>'
    
    html_parts = []
    
    for k in added_keys:
        val = comp_map[k]
        display_val = (val[:20] + '..') if len(val) > 20 else val
        html_parts.append(
            f'<span class="diff-tag diff-add" title="相对于当前版本，此处新增了: {val}">'
            f'<i class="bi bi-plus"></i>{display_val}</span>'
        )
        
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
        # 【修改】使用 Case/When 优先获取 is_main_variant=True 的 ID
        group_stats = PromptGroup.objects.values('group_id').annotate(
            main_id=Max(Case(When(is_main_variant=True, then='id'), output_field=IntegerField())),
            latest_id=Max('id'),
            count=Count('id')
        )
        final_ids = []
        for s in group_stats:
            # 如果设定了主版本(main_id)，就用它；否则用最新的(latest_id)
            target_id = s['main_id'] if s['main_id'] else s['latest_id']
            final_ids.append(target_id)
            version_counts[target_id] = s['count']
        queryset = queryset.filter(id__in=final_ids)

    tags_bar = get_tags_bar_data()
    paginator = Paginator(queryset, 12)
    page_number = request.GET.get('page')
    page = paginator.get_page(page_number)
    page_obj = paginator.get_page(page_number)
    page_range = page.paginator.get_elided_page_range(page.number, on_each_side=2, on_ends=1)
    total_groups_count = PromptGroup.objects.values('group_id').distinct().count()

    for group in page_obj:
        group.version_count = version_counts.get(group.id, 0)

    return render(request, 'gallery/home.html', {
        'groups': page,
        'page_obj': page_obj,
        'page_range': page_range,
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
    group = get_object_or_404(
        PromptGroup.objects.prefetch_related(
            'tags', 
            Prefetch('images', queryset=ImageItem.objects.order_by('-id')),
            'references'
        ), 
        pk=pk
    )
    # === 上一篇/下一篇 导航逻辑 (Context Aware) ===
    # 获取上下文参数
    query = request.GET.get('q')
    filter_type = request.GET.get('filter')
    
    # 构造基础查询集 (Nav QuerySet)
    nav_qs = PromptGroup.objects.all()
    
    # 1. 复刻首页的搜索逻辑
    if query:
        nav_qs = nav_qs.filter(
            Q(title__icontains=query) |
            Q(prompt_text__icontains=query) |
            Q(prompt_text_zh__icontains=query) |
            Q(tags__name__icontains=query)
        ).distinct()
        
    # 2. 复刻首页的筛选逻辑
    if filter_type == 'liked':
        nav_qs = nav_qs.filter(is_liked=True)
        
    # 3. 默认模式下的去重逻辑 (仅在无搜索、无筛选时应用)
    # 如果用户在搜索模式下，可能希望看到所有命中的版本，所以搜索时不进行去重
    is_default_view = (not query and not filter_type)
    
    if is_default_view:
        # 获取代表ID列表 (主版本 or 最新版本)
        group_stats = PromptGroup.objects.values('group_id').annotate(
            main_id=Max(Case(When(is_main_variant=True, then='id'), output_field=IntegerField())),
            latest_id=Max('id')
        )
        target_ids = [ (s['main_id'] or s['latest_id']) for s in group_stats ]
        nav_qs = nav_qs.filter(id__in=target_ids)

    # 4. 计算 上一篇 (Previous = ID更的大 = 更晚创建)
    # 如果是默认视图，额外排除同 Group 的 ID (虽然 dedupe 理论上已处理，加一层保险)
    prev_qs = nav_qs.filter(id__gt=pk)
    if is_default_view:
        prev_qs = prev_qs.exclude(group_id=group.group_id)
    prev_group = prev_qs.order_by('id').first() # 找比当前pk大的里面最小的那个
    
    # 5. 计算 下一篇 (Next = ID更小 = 更早创建)
    next_qs = nav_qs.filter(id__lt=pk)
    if is_default_view:
        next_qs = next_qs.exclude(group_id=group.group_id)
    next_group = next_qs.order_by('-id').first() # 找比当前pk小的里面最大的那个

    # 拆分图片和视频
    all_items = group.images.all()
    images_list = [item for item in all_items if not item.is_video]
    videos_list = [item for item in all_items if item.is_video]
    
    tags_list = list(group.tags.all())
    model_name = group.model_info
    if model_name:
        tags_list.sort(key=lambda t: 0 if t.name == model_name else 1)
    
    all_tags = Tag.objects.annotate(usage_count=Count('promptgroup')).order_by('-usage_count', 'name')[:500]

    siblings_qs = PromptGroup.objects.filter(
        group_id=group.group_id
    ).exclude(pk=group.pk).order_by('-created_at')
    
    siblings = []
    current_prompt = group.prompt_text or ""
    
    for sib in siblings_qs:
        sib_prompt = sib.prompt_text or ""
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
        'search_query': request.GET.get('q'),
        'images_list': images_list,
        'videos_list': videos_list,
        'prev_group': prev_group,
        'next_group': next_group,
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

        source_group_id = request.POST.get('source_group_id')
        print(f"DEBUG: 尝试克隆参考图，Source ID: {source_group_id}") # 调试打印 1
        
        if source_group_id:
            try:
                source_group = PromptGroup.objects.get(pk=source_group_id)
                refs = source_group.references.all()
                print(f"DEBUG: 找到源参考图数量: {refs.count()}") # 调试打印 2
                
                for ref in refs:
                    if ref.image:
                        print(f"DEBUG: 正在复制图片: {ref.image.name}") # 调试打印 3
                        
                        # 创建新对象
                        new_ref = ReferenceItem(group=group)
                        
                        # 显式打开文件（使用 with 语句更安全）
                        try:
                            # 必须确保文件存在
                            if not ref.image.storage.exists(ref.image.name):
                                print(f"DEBUG: 原文件不存在于磁盘: {ref.image.name}")
                                continue

                            with ref.image.open('rb') as f:
                                # 读取内容
                                file_content = ContentFile(f.read())
                                # 生成新文件名
                                original_name = os.path.basename(ref.image.name)
                                # 保存
                                new_ref.image.save(f"copy_{original_name}", file_content, save=True)
                                print("DEBUG: 复制成功")
                                
                        except Exception as inner_e:
                            print(f"DEBUG: 复制单个文件失败: {inner_e}")
                            # 这里不要 raise，防止一张图失败导致整个流程失败
                            # 但一定要打印出来看是什么错

            except PromptGroup.DoesNotExist:
                print("DEBUG: 源组 ID 未找到")
        else:
            print("DEBUG: 未接收到 source_group_id，前端可能未传递")

        created_image_ids = []
        
        direct_files = request.FILES.getlist('upload_images')
        for f in direct_files:
            img_item = ImageItem(group=group, image=f)
            img_item.save()
            created_image_ids.append(img_item.id)

        batch_id = request.POST.get('batch_id')
        server_file_names = request.POST.getlist('selected_files')
        
        if batch_id and server_file_names:
            temp_ids = confirm_upload_images(batch_id, server_file_names, group)
            created_image_ids.extend(temp_ids)
            
        ref_files = request.FILES.getlist('upload_references')
        for rf in ref_files:
            ReferenceItem.objects.create(group=group, image=rf)

        if not created_image_ids:
            pass
        else:
            trigger_background_processing(created_image_ids)
            messages.success(request, f"成功发布！包含 {len(created_image_ids)} 个文件，系统正在后台处理索引。")

        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or \
                  request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'

        if is_ajax:
            group.version_count = 1 
            html = render_to_string('gallery/components/home_group_card.html', {
                'group': group,
            }, request=request)
            return JsonResponse({
                'status': 'success',
                'html': html,
                'message': f"成功发布！包含 {len(created_image_ids)} 个文件"
            })

        return redirect('home')

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
        
        # === 【新增】处理 template_id 预填充 ===
        template_id = request.GET.get('template_id')
        initial_data = {}
        source_group = None
        
        if template_id:
            try:
                source_group = PromptGroup.objects.get(pk=template_id)
                initial_data = {
                    'title': source_group.title, # 可以选择加上 ' (新模型)' 后缀
                    'prompt_text': source_group.prompt_text,
                    'prompt_text_zh': source_group.prompt_text_zh,
                    'negative_prompt': source_group.negative_prompt,
                    'tags': source_group.tags.all(),
                    # 注意：不预填充 model_info，强制用户选择新模型
                }
            except PromptGroup.DoesNotExist:
                pass

        form = PromptGroupForm(initial=initial_data)
        existing_titles = PromptGroup.objects.values_list('title', flat=True).distinct().order_by('title')
        all_models = AIModel.objects.all()

        temp_files_json = json.dumps(temp_files_preview)

        return render(request, 'gallery/upload.html', {
            'form': form,
            'existing_titles': existing_titles,
            'all_models': all_models,
            'batch_id': batch_id,
            'temp_files': temp_files_json,
            'source_group': source_group,
        })


@csrf_exempt
def check_duplicates(request):
    """全库查重接口 (修复版 - 修正 update 报错)"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '仅支持 POST 请求'})

    files = request.FILES.getlist('images')
    if not files:
        return JsonResponse({'status': 'error', 'message': '未检测到上传文件'})

    # 1. 创建临时保存目录
    batch_id = uuid.uuid4().hex
    temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_uploads', batch_id)
    os.makedirs(temp_dir, exist_ok=True)

    results = []

    try:
        for file in files:
            # 2. 保存文件到临时目录
            file_path = os.path.join(temp_dir, file.name)
            with open(file_path, 'wb+') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)  # 【修正】这里必须用 write，不能用 update

            # 3. 计算哈希 (确保引入了 calculate_file_hash)
            # 注意：calculate_file_hash 通常需要文件路径或打开的文件对象，
            # 这里传入 file_path 比较稳妥，因为 file 对象指针可能已经到底了
            file_hash = calculate_file_hash(file_path) 
            
            # 构造 URL
            relative_path = f"temp_uploads/{batch_id}/{file.name}"
            file_url = f"{settings.MEDIA_URL}{relative_path}"

            # 4. 查库比对
            duplicates = ImageItem.objects.filter(image_hash=file_hash)
            
            is_duplicate = duplicates.exists()
            dup_info = []
            
            if is_duplicate:
                for dup in duplicates:
                    dup_info.append({
                        'id': dup.id,
                        'group_id': dup.group.id, # 确保前端用 group_id 跳转详情页
                        'group_title': dup.group.title,
                        'is_video': dup.is_video,
                        'url': dup.thumbnail.url if dup.thumbnail else dup.image.url
                    })

            results.append({
                'filename': file.name,
                'status': 'duplicate' if is_duplicate else 'pass',
                'url': file_url,
                'thumbnail_url': file_url, # 前端字段兼容
                'duplicates': dup_info
            })
            
    except Exception as e:
        import traceback
        traceback.print_exc() # 打印详细错误堆栈到控制台，方便调试
        shutil.rmtree(temp_dir, ignore_errors=True)
        return JsonResponse({'status': 'error', 'message': str(e)})

    return JsonResponse({
        'status': 'success', 
        'batch_id': batch_id, 
        'results': results,
        'has_duplicate': any(r['status'] == 'duplicate' for r in results)
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
                    # 检查组内排重
                    existing_img = ImageItem.objects.filter(group=group, image_hash=file_hash).first()
                    
                    if existing_img:
                        duplicates.append({
                            'name': f.name,
                            'existing_group_title': existing_img.group.title,
                            'existing_url': existing_img.image.url
                        })
                    else:
                        img_item = ImageItem(group=group, image=f)
                        img_item.image_hash = file_hash
                        img_item.save()
                        created_ids.append(img_item.id)
                        uploaded_count += 1
            
            if created_ids:
                trigger_background_processing(created_ids)

            if is_ajax:
                # 重新查询以确保数据完整
                new_images = ImageItem.objects.filter(id__in=created_ids).order_by('id')
                new_images_data = []
                html_list = []
                
                for img in new_images:
                    # 【核心修复】上传后立即显示时，直接使用原图 URL，避免缩略图未生成导致的白图
                    # 原来的 try-except 逻辑虽然有兜底，但 ImageKit 可能会返回一个存在的空文件路径导致白图
                    safe_url = img.image.url if img.image else ""

                    new_images_data.append({
                        'id': img.pk,
                        'url': img.image.url, 
                        'isLiked': img.is_liked,
                        'is_video': img.is_video,
                        'isVideo': img.is_video 
                    })
                    
                    html = render_to_string('gallery/components/detail_image_card.html', {
                        'img': img, 
                        'force_image_url': safe_url  # 强制传入原图 URL
                    }, request=request)
                    html_list.append(html)

                msg = f"成功添加 {uploaded_count} 个文件"
                if duplicates:
                    msg += f"，忽略 {len(duplicates)} 个重复文件"

                return JsonResponse({
                    'status': 'success' if not duplicates else 'warning',
                    'message': msg,
                    'uploaded_count': uploaded_count,
                    'duplicates': duplicates,
                    'new_images_html': html_list,
                    'new_images_data': new_images_data,
                    'type': 'gen'
                })
            
            # 非 AJAX 请求的回退
            if duplicates:
                messages.warning(request, f"成功添加 {uploaded_count} 个文件，忽略 {len(duplicates)} 个重复文件")
            else:
                messages.success(request, f"成功添加 {uploaded_count} 个文件")
        
        except Exception as e:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
            raise e
            
    return redirect('detail', pk=pk)


def add_references_to_group(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    
    if request.method == 'POST':
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or \
                  request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'

        try:
            files = request.FILES.getlist('new_references')
            new_refs = []
            if files:
                for f in files:
                    ref = ReferenceItem.objects.create(group=group, image=f)
                    new_refs.append(ref)
            
            if is_ajax:
                html_list = []
                for ref in new_refs:
                    html = render_to_string('gallery/components/detail_reference_item.html', {
                        'ref': ref,
                    }, request=request)
                    html_list.append(html)
                
                return JsonResponse({
                    'status': 'success',
                    'message': f"成功添加 {len(new_refs)} 个参考文件",
                    'uploaded_count': len(new_refs),
                    'new_references_html': html_list,
                    'type': 'ref'
                })
        except Exception as e:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
            raise e

    return redirect('detail', pk=pk)


def delete_group(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    if request.method == 'POST':
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or \
                  request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'

        for img in group.images.all():
            if img.image:
                img.image.delete(save=False)
        for ref in group.references.all():
            if ref.image:
                ref.image.delete(save=False)
        group.delete()
        
        if is_ajax:
            return JsonResponse({'status': 'success', 'type': 'group'})

        messages.success(request, "已删除该组内容")
        return redirect('home')
        
    return redirect('detail', pk=pk)


def delete_image(request, pk):
    image_item = get_object_or_404(ImageItem, pk=pk)
    group_pk = image_item.group.pk
    
    if request.method == 'POST':
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or \
                  request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
                  
        try:
            image_item.image.delete(save=False)
            image_item.delete()
            
            if is_ajax:
                return JsonResponse({'status': 'success', 'pk': pk})
        except Exception as e:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': str(e)})
            
    return redirect('detail', pk=group_pk)


def delete_reference(request, pk):
    item = get_object_or_404(ReferenceItem, pk=pk)
    group_pk = item.group.pk
    
    if request.method == 'POST':
        is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or \
                  request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
                  
        try:
            item.image.delete(save=False)
            item.delete()
            
            if is_ajax:
                return JsonResponse({'status': 'success', 'pk': pk})
        except Exception as e:
            if is_ajax:
                return JsonResponse({'status': 'error', 'message': str(e)})
            
    return redirect('detail', pk=group_pk)


@require_POST
def update_group_prompts(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    try:
        data = json.loads(request.body)
        if 'title' in data:
            group.title = data['title']
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
        main_id=Max(Case(When(is_main_variant=True, then='id'), output_field=IntegerField())),
        max_id=Max('id'),     
        count=Count('id')     
    )
    
    # 优先取 main_id
    target_ids = [ (item['main_id'] or item['max_id']) for item in group_stats ]
    # 建立 ID -> Count 映射
    count_map = { (item['main_id'] or item['max_id']): item['count'] for item in group_stats }
    final_qs = PromptGroup.objects.filter(id__in=target_ids).order_by('-id')
    
    paginator = Paginator(final_qs, 20)
    page = paginator.get_page(page_num)
    
    data = []
    for group in page:
        cover_url = ""
        ## 【修改逻辑】优先取指定的 cover_image，没有则按原逻辑找第一张图
        cover_img = group.cover_image
        
        if not cover_img:
            images = group.images.all()
            # 优先找非视频图片
            for img in images:
                if not img.is_video:
                    cover_img = img
                    break
            # 兜底
            if not cover_img and images.exists():
                cover_img = images.first()

        if cover_img:
            try:
                # 再次检测，防止视频调用 thumbnail 报错
                if not cover_img.is_video and cover_img.thumbnail:
                    cover_url = cover_img.thumbnail.url
                else:
                    cover_url = cover_img.image.url
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
    
@require_POST
def unlink_group_relation(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    group.group_id = uuid.uuid4()
    group.save()
    return JsonResponse({'status': 'success'})

@require_POST
def link_group_relation(request, pk):
    current_group = get_object_or_404(PromptGroup, pk=pk)
    try:
        data = json.loads(request.body)
        
        target_ids = data.get('target_ids', [])
        if 'target_id' in data:
            target_ids.append(data['target_id'])
            
        if not target_ids:
             return JsonResponse({'status': 'error', 'message': '未选择任何版本'})

        # 【核心修复】不仅获取选中的 ID，还获取它们代表的整个家族 group_id
        target_reps = PromptGroup.objects.filter(id__in=target_ids).exclude(id=current_group.id)
        target_group_ids = target_reps.values_list('group_id', flat=True).distinct()
        
        # 将所有属于这些 group_id 的记录统一迁移
        groups_to_update = PromptGroup.objects.filter(group_id__in=target_group_ids).exclude(id=current_group.id)
        
        count = groups_to_update.update(group_id=current_group.group_id)
        
        return JsonResponse({'status': 'success', 'count': count})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
    
@require_POST
def batch_delete_images(request):
    """批量删除图片接口"""
    try:
        data = json.loads(request.body)
        image_ids = data.get('image_ids', [])
        
        if not image_ids:
            return JsonResponse({'status': 'error', 'message': '未选择任何图片'})

        # 查找要删除的对象
        images = ImageItem.objects.filter(id__in=image_ids)
        deleted_count = 0
        
        for img in images:
            # 手动删除文件，确保不留垃圾文件（参考原 delete_image 逻辑）
            if img.image:
                img.image.delete(save=False)
            img.delete()
            deleted_count += 1
            
        return JsonResponse({'status': 'success', 'count': deleted_count})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
# 【新增】设置封面视图
@require_POST
def set_group_cover(request, group_id, image_id):
    group = get_object_or_404(PromptGroup, pk=group_id)
    image = get_object_or_404(ImageItem, pk=image_id)
    
    # 安全检查：确保图片属于该组
    if image.group_id != group.id:
        return JsonResponse({'status': 'error', 'message': '图片不属于该组'})
    
    group.cover_image = image
    group.save()
    return JsonResponse({'status': 'success'})

@require_GET
def get_similar_candidates(request, pk):
    """获取相似提示词的推荐候选 (用于关联版本)"""
    try:
        current_group = PromptGroup.objects.get(pk=pk)
    except PromptGroup.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Group not found'})

    my_content = (current_group.prompt_text or "").strip().lower()
    if len(my_content) < 5:
         return JsonResponse({'status': 'success', 'results': []})

    # 1. 获取所有组的最新版本 ID (避免推荐同组的历史版本)
    group_stats = PromptGroup.objects.values('group_id').annotate(max_id=Max('id'))
    latest_ids = [item['max_id'] for item in group_stats]
    
    # 2. 查询候选集 (排除当前组，限制数量以保证性能)
    # 取最新的 1000 个组作为候选池
    candidates = PromptGroup.objects.filter(id__in=latest_ids).exclude(group_id=current_group.group_id).order_by('-id')[:1000]
    
    recommendations = []
    
    for other in candidates:
        other_content = (other.prompt_text or "").strip().lower()
        if not other_content: continue
        
        # 简单预筛: 长度差异过大直接跳过
        max_len = max(len(my_content), len(other_content))
        if max_len == 0: continue
        if abs(len(my_content) - len(other_content)) > max_len * 0.7: 
            continue

        # 计算相似度
        ratio = difflib.SequenceMatcher(None, my_content, other_content).ratio()
        
        # 相似度 > 30% 即可推荐 (关联推荐可以放宽一点)
        if ratio > 0.3: 
            recommendations.append((ratio, other))
            
    # 按相似度降序排列，取前 20 个
    recommendations.sort(key=lambda x: x[0], reverse=True)
    top_recs = recommendations[:20]
    
    results = []
    for ratio, group in top_recs:
        # 复用封面获取逻辑
        cover_url = ""
        cover_img = group.cover_image # 优先用封面
        if not cover_img:
            images = group.images.all()
            for img in images:
                if not img.is_video:
                    cover_img = img
                    break
            if not cover_img and images.exists():
                cover_img = images.first()
        
        if cover_img:
             try:
                if not cover_img.is_video and cover_img.thumbnail:
                    cover_url = cover_img.thumbnail.url
                else:
                    cover_url = cover_img.image.url
             except:
                 pass
                 
        results.append({
            'id': group.id,
            'title': group.title,
            'prompt_text': group.prompt_text[:200] if group.prompt_text else '',
            'cover_url': cover_url,
            'similarity': f"{int(ratio*100)}%" # 返回相似度百分比
        })
        
    return JsonResponse({'status': 'success', 'results': results})

@require_POST
def set_main_variant(request, pk):
    """将指定 PromptGroup 设为该系列的‘主版本’ (首页展示)"""
    target = get_object_or_404(PromptGroup, pk=pk)
    
    # 1. 将同组的其他版本标记取消
    PromptGroup.objects.filter(group_id=target.group_id).update(is_main_variant=False)
    
    # 2. 将当前版本设为主版本
    target.is_main_variant = True
    target.save()
    
    return JsonResponse({'status': 'success'})