from django.contrib import admin
from .models import Collection, SourceRoot, VisualResource

@admin.register(SourceRoot)
class SourceRootAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'root_path', 'is_enabled', 'last_synced_at', 'updated_at')
    list_filter = ('is_enabled',)
    search_fields = ('name', 'root_path')
    list_display_links = ('id', 'name')
    readonly_fields = ('last_synced_at', 'created_at', 'updated_at')
    list_per_page = 20


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'created_at')
    search_fields = ('name', 'description')
    list_display_links = ('id', 'name')
    list_per_page = 20


@admin.register(VisualResource)
class VisualResourceAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'resource_type', 'status', 'source_root', 'last_synced_at', 'is_liked', 'is_missing', 'created_at')
    list_filter = ('resource_type', 'status', 'is_liked', 'is_missing', 'source_root', 'created_at')
    search_fields = ('title', 'file_path', 'relative_path', 'file_hash')
    list_display_links = ('id', 'title')
    filter_horizontal = ('tags', 'collections')
    readonly_fields = ('file_size', 'mime_type', 'extension', 'modified_at', 'indexed_at', 'last_synced_at', 'created_at', 'updated_at', 'last_error')
    list_per_page = 30