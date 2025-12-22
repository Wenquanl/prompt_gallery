from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    # 【新增】单独的喜欢的图片墙页面
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
    
    # 【新增】点赞接口 (API)
    path('toggle-like-group/<int:pk>/', views.toggle_like_group, name='toggle_like_group'),
    path('toggle-like-image/<int:pk>/', views.toggle_like_image, name='toggle_like_image'),
    # 【新增】更新提示词接口
    path('update-prompts/<int:pk>/', views.update_group_prompts, name='update_group_prompts'),
]