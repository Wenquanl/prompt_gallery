# visuals/urls.py
from django.urls import path
from . import views

# 给这个 app 的路由起个命名空间，防止和其他 app 里的名字冲突
app_name = 'visuals' 

urlpatterns = [
    path('', views.visuals_view, name='home'),
    path('sources/', views.source_roots_view, name='sources'),
    path('sources/progress/', views.sources_progress, name='sources_progress'),
    path('sources/create/', views.create_source_root, name='create_source_root'),
    path('sources/pick/', views.pick_source_root, name='pick_source_root'),
    path('sources/<int:source_id>/update/', views.update_source_root, name='update_source_root'),
    path('sources/<int:source_id>/resource-action/', views.source_root_resource_action, name='source_root_resource_action'),
    path('sources/<int:source_id>/delete/', views.delete_source_root, name='delete_source_root'),
    path('resource/<int:resource_id>/', views.resource_detail, name='resource_detail'),
    path('resource/<int:resource_id>/open-explorer/', views.open_resource_in_explorer, name='open_resource_in_explorer'),
    path('preview/<int:resource_id>/', views.preview_resource, name='preview_resource'),
    path('stream/<int:video_id>/', views.stream_video, name='stream_video'),
    path('toggle-like/<int:resource_id>/', views.toggle_like, name='toggle_like'),
    path('batch/', views.batch_action, name='batch_action'),
    path('sync-all/', views.sync_all_sources_now, name='sync_all_sources_now'),
    path('sync-source/<int:source_id>/', views.sync_source_now, name='sync_source_now'),
    path('sync-resource/<int:resource_id>/', views.sync_resource_now, name='sync_resource_now'),
    path('duplicates/', views.duplicates, name='duplicates'),
]