from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator
from django.db.models import Q
from .models import PromptGroup, ImageItem, Tag, AIModel, ReferenceItem
from .forms import PromptGroupForm

def home(request):
    queryset = PromptGroup.objects.all()
    query = request.GET.get('q')

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
        'search_query': query 
    })

def detail(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    
    # 标签排序
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

# 【核心修改】上传视图：支持 next 参数实现“从哪来回哪去”
def upload(request):
    # 1. 获取来源地址 (优先级: POST参数 > GET参数 > HTTP_REFERER > 首页)
    # 这样即使表单提交失败重新渲染，也能记住最开始是从哪来的
    next_url = request.POST.get('next') or request.GET.get('next') or request.META.get('HTTP_REFERER') or '/'
    
    # 防止 next_url 是 /upload/ 自身导致死循环
    if '/upload/' in next_url:
        next_url = '/'

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
            
            # 保存生成图
            files = request.FILES.getlist('upload_images')
            for f in files:
                ImageItem.objects.create(group=group, image=f)

            # 保存参考图
            ref_files = request.FILES.getlist('upload_references')
            for f in ref_files:
                ReferenceItem.objects.create(group=group, image=f)
            
            # 【核心】上传成功后，跳转回 next_url (比如刚才的详情页或列表页)
            return redirect(next_url)
    else:
        form = PromptGroupForm()
    
    return render(request, 'gallery/upload.html', {
        'form': form,
        'next_url': next_url  # 把来源地址传给模板，用于"返回"按钮
    })

def add_images_to_group(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    if request.method == 'POST':
        files = request.FILES.getlist('new_images')
        if files:
            for f in files:
                ImageItem.objects.create(group=group, image=f)
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