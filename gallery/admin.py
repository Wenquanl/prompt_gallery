from django.contrib import admin
from .models import PromptGroup, ImageItem, Tag, AIModel, Character
from .forms import PromptGroupForm

# 注册 AI 模型管理
@admin.register(AIModel)
class AIModelAdmin(admin.ModelAdmin):
    list_display = ('name', 'order')
    list_editable = ('order',)

@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    search_fields = ['name']

@admin.register(Character)
class CharacterAdmin(admin.ModelAdmin):
    list_display = ('name', 'order')
    list_editable = ('order',)
    search_fields = ['name']

class ImageItemInline(admin.TabularInline):
    model = ImageItem
    extra = 0
    readonly_fields = ('image_preview',)
    def image_preview(self, obj):
        return obj.image.name
    image_preview.short_description = "文件名"

@admin.register(PromptGroup)
class PromptGroupAdmin(admin.ModelAdmin):
    form = PromptGroupForm
    inlines = [ImageItemInline]
    list_display = ('title', 'created_at', 'image_count', 'display_characters', 'display_tags')
    search_fields = ['title', 'prompt_text', 'tags__name', 'characters__name']
    filter_horizontal = ('tags', 'characters')

    def image_count(self, obj):
        return obj.images.count()
    image_count.short_description = "图片数"

    def display_tags(self, obj):
        return ", ".join([t.name for t in obj.tags.all()])
    display_tags.short_description = "标签"

    def display_characters(self, obj):
        return ", ".join([c.name for c in obj.characters.all()])
    display_characters.short_description = "包含人物"

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        files = form.cleaned_data.get('upload_images')
        if files:
            for f in files:
                ImageItem.objects.create(group=obj, image=f)

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        context.update({'is_multipart': True})
        return super().render_change_form(request, context, add, change, form_url, obj)