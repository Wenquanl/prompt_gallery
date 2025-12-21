from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('image/<int:pk>/', views.detail, name='detail'),
    path('upload/', views.upload, name='upload'),
    
    # 删除相关
    path('delete-group/<int:pk>/', views.delete_group, name='delete_group'),
    path('delete-image/<int:pk>/', views.delete_image, name='delete_image'),
    path('delete-reference/<int:pk>/', views.delete_reference, name='delete_reference'), # 新增
    
    # 添加相关
    path('add-images/<int:pk>/', views.add_images_to_group, name='add_images'),
    path('add-references/<int:pk>/', views.add_references_to_group, name='add_references'), # 新增
]