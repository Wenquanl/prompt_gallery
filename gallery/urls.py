from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    # 单独的喜欢的图片墙页面
    path('liked-images/', views.liked_images_gallery, name='liked_images_gallery'),
    
    path('image/<int:pk>/', views.detail, name='detail'),
    path('upload/', views.upload, name='upload'),
    
    # 删除相关
    path('delete-group/<int:pk>/', views.delete_group, name='delete_group'),
    path('delete-image/<int:pk>/', views.delete_image, name='delete_image'),
    path('delete-reference/<int:pk>/', views.delete_reference, name='delete_reference'),
    
    # 添加相关
    path('add-images/<int:pk>/', views.add_images_to_group, name='add_images'),
    path('add-references/<int:pk>/', views.add_references_to_group, name='add_references'),
    
    # 标签管理 (新增)
    path('add-tag/<int:pk>/', views.add_tag_to_group, name='add_tag'),
    path('remove-tag/<int:pk>/', views.remove_tag_from_group, name='remove_tag'),
    
    # 点赞接口 (API)
    path('toggle-like-group/<int:pk>/', views.toggle_like_group, name='toggle_like_group'),
    path('toggle-like-image/<int:pk>/', views.toggle_like_image, name='toggle_like_image'),
    # 更新提示词接口
    path('update-prompts/<int:pk>/', views.update_group_prompts, name='update_group_prompts'),
    # 查重接口
    path('check-duplicates/', views.check_duplicates, name='check_duplicates'),
    # 【新增】合并功能相关接口
    path('api/groups/', views.group_list_api, name='group_list_api'),
    path('api/merge-groups/', views.merge_groups, name='merge_groups'),
    path('api/unlink-group/<int:pk>/', views.unlink_group_relation, name='unlink_group'),
    path('api/link-group/<int:pk>/', views.link_group_relation, name='link_group'),
    path('api/batch-delete/', views.batch_delete_images, name='batch_delete_images'), 
]