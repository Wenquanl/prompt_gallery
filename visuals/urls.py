# visuals/urls.py
from django.urls import path
from . import views

# 给这个 app 的路由起个命名空间，防止和其他 app 里的名字冲突
app_name = 'visuals' 

urlpatterns = [
    # 这里的 '' 代表匹配 /visuals/ 后面的空路径
    path('', views.visuals_view, name='home'), 
    path('stream/<int:video_id>/', views.stream_video, name='stream_video'),
]