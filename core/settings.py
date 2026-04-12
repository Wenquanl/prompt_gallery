"""
Django settings for prompt_gallery project.
"""
import os
from pathlib import Path
from dotenv import load_dotenv  # 新增: 引入 dotenv

# 加载 .env 文件
load_dotenv()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# =========================================================
# 安全性配置 (Safety & Security)
# =========================================================

# 从环境变量读取 SECRET_KEY，如果没有则使用开发默认值 (仅用于开发环境)
SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-default-key-change-me-in-prod')

# 从环境变量读取 DEBUG，默认为 False，只有设为 'True' 时才开启
DEBUG = os.getenv('DJANGO_DEBUG', 'False') == 'True'

ALLOWED_HOSTS = ['*']

# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    
    # Third party
    'imagekit',
    
    # Local apps
    'gallery.apps.GalleryConfig',
    'visuals',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, 'templates')],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'

# Database
# https://docs.djangoproject.com/en/4.2/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# Password validation
# https://docs.djangoproject.com/en/4.2/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/4.2/topics/i18n/

LANGUAGE_CODE = 'zh-hans'

TIME_ZONE = 'Asia/Shanghai'

USE_I18N = True

USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/4.2/howto/static-files/

STATIC_URL = '/static/'
import os
# 设置静态文件收集的绝对路径
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')

# 开启 WhiteNoise 的高效压缩和缓存（可选，强烈推荐）
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'
STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static')
]

# Media files (User uploads)
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
VISUALS_PREVIEW_ROOT = os.path.join(MEDIA_ROOT, 'visuals_previews')
VISUALS_FFMPEG_EXE = os.getenv('VISUALS_FFMPEG_EXE', 'ffmpeg')
VISUALS_FFPROBE_EXE = os.getenv('VISUALS_FFPROBE_EXE', 'ffprobe')
VISUALS_SYNC_MINUTES = int(os.getenv('VISUALS_SYNC_MINUTES', '5'))
MEILI_URL = os.getenv('MEILI_URL', 'http://127.0.0.1:7700')
MEILI_KEY = os.getenv('MEILI_KEY', 'dq49aaqs-RYHbIfKGMOFJRrfco3jP-0Ubj4gcX9caBc')

# Default primary key field type
# https://docs.djangoproject.com/en/4.2/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# 1. 注册 Huey 应用
if 'huey.contrib.djhuey' not in INSTALLED_APPS: # 防止重复添加
    INSTALLED_APPS.append('huey.contrib.djhuey') # (Assuming it's a list)

# 2. Huey 队列配置（使用 SQLite 作为中间件，Windows 极其友好，无需装 Redis）
HUEY = {
    'huey_class': 'huey.SqliteHuey',  
    'name': 'prompt_gallery_tasks',
    'results': True,
    'store_none': False,
    'immediate': False,  # 设为 False 表示真正使用异步。如果开发调试时想看报错，可临时改为 True
    'filename': os.path.join(BASE_DIR, 'huey_tasks.sqlite3'), # 在项目根目录生成独立的任务数据库
}

# 3. 告诉 Caddy 内部重定向的 Header 名称 (后续会用到)
# Nginx 默认是 X-Accel-Redirect，Caddy 可以自定义或复用
SENDFILE_HEADER = 'X-Accel-Redirect'