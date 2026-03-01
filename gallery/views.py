import os
import time
import difflib
import uuid
import json
import re
import shutil
import fal_client
import requests
import base64
import warnings # 新增引入 warnings 模块
from urllib3.exceptions import InsecureRequestWarning # 引入具体的警告类型
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse
from django.db.models import Q, Count, Case, When, IntegerField, Max, Prefetch
from django.db import transaction
from django.core.files.base import ContentFile
from django.core.paginator import Paginator
from django.views.decorators.http import require_GET, require_POST
from django.core.cache import cache
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from .models import ImageItem, PromptGroup, Tag, AIModel, ReferenceItem, Character
from .forms import PromptGroupForm
from .ai_utils import search_similar_images, generate_title_with_local_llm
from .ai_providers import get_ai_provider

# === 引入 Service 层 ===
from .services import (
    get_temp_dir, 
    calculate_file_hash, 
    trigger_background_processing,
    confirm_upload_images
)

# ==========================================
# 终极配置中心 (Single Source of Truth)
# ==========================================
warnings.filterwarnings("ignore", category=InsecureRequestWarning)
AI_STUDIO_CONFIG = {
    # 1. 大类定义
    'categories': [
        {'id': 'multi', 'title': '🟢 多图融合', 'img_max': 10, 'img_help': '当前为多图模式：按住 Ctrl 键可多选 (最多10张)'},
        {'id': 'i2i', 'title': '🔵 图生图', 'img_max': 1, 'img_help': '当前为单图模式：请上传 1 张参考图片'},
        {'id': 't2i', 'title': '🟠 文生图', 'img_max': 0, 'img_help': '纯文本模式，无需传图'},
    ],
    # 2. 具体模型定义
    'models': {
        'flux-dev': {
            'provider': 'fal_ai',
            'category': 't2i',
            'endpoint': 'fal-ai/flux/dev',
            'title': 'Flux Dev',
            'desc': '推荐，生成质量极高，语义理解精准',
            'params': [
                {'id': 'image_size', 'label': '图片画幅 (Size)', 'type': 'select', 'options': [
                    {'value': 'landscape_4_3', 'text': '横版 4:3 (默认)'},
                    {'value': 'portrait_4_3', 'text': '竖版 3:4'},
                    {'value': 'square_hd', 'text': '正方形 HD'}
                ], 'default': 'landscape_4_3'},
                {'id': 'num_inference_steps', 'label': '生成步数 (Steps)', 'type': 'range', 'min': 20, 'max': 50, 'step': 1, 'default': 28}
            ]
        },
        'flux-dev-i2i': {
            'provider': 'fal_ai',
            'category': 'i2i',
            'endpoint': 'fal-ai/flux/dev/image-to-image',
            'title': 'Flux i2i',
            'desc': 'Flux Dev 的图生图强化变体',
            'params': [
                {'id': 'strength', 'label': '重绘幅度 (Strength)', 'type': 'range', 'min': 0.1, 'max': 1.0, 'step': 0.05, 'default': 0.75},
                {'id': 'num_inference_steps', 'label': '生成步数 (Steps)', 'type': 'range', 'min': 20, 'max': 50, 'step': 1, 'default': 28}
            ]
        },
        'seedream-5.0-lite-official': {
            'provider': 'volcengine',
            'category': 'multi',
            'endpoint': 'doubao-seedream-5-0-260128', 
            'title': 'Seedream 5.0 Lite (官方)',
            'desc': '字节官方最新 API，支持多图融合、组图生成与联网搜索',
            'params': [
                {'id': 'max_images', 'label': '生成组图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'image_size', 'label': '生成尺寸 (Size)', 'type': 'select', 'options': [
                    {'value': '2K', 'text': '2K (默认)'},
                    {'value': '3K', 'text': '3K (超清)'},
                ], 'default': '2K'},
                {'id': 'prompt_aspect_ratio', 'label': '画面比例 (仅追加到提示词)', 'type': 'select', 'options': [
                    {'value': 'none', 'text': '不指定'},
                    {'value': '1:1', 'text': '1:1 (正方形)'},
                    {'value': '3:4', 'text': '3:4 (竖版)'},
                    {'value': '4:3', 'text': '4:3 (横版)'},
                    {'value': '16:9', 'text': '16:9 (横版)'},
                    {'value': '9:16', 'text': '9:16 (竖版)'},
                    {'value': '3:2', 'text': '3:2 (横版)'},
                    {'value': '2:3', 'text': '2:3 (竖版)'},
                    {'value': '21:9', 'text': '21:9 (宽屏)'}
                ], 'default': '9:16'},
                {'id': 'output_format', 'label': '输出格式', 'type': 'select', 'options': [
                    {'value': 'png', 'text': 'PNG'},
                    {'value': 'jpeg', 'text': 'JPEG'}
                ], 'default': 'png'},
                {'id': 'watermark', 'label': '添加官方水印', 'type': 'checkbox', 'default': False},
                {'id': 'enable_web_search', 'label': '开启联网搜索', 'type': 'checkbox', 'default': False, 'help_text': '开启后模型会根据提示词自主搜索互联网内容（如近期天气、新闻等）'}
            ]
        },
        'seedream-4.5-official': {
            'provider': 'volcengine',
            'category': 'multi',
            'endpoint': 'doubao-seedream-4-5-251128',
            'title': 'Seedream 4.5 (官方)',
            'desc': '字节官方 API，专注高质量图像输出',
            'params': [
                {'id': 'max_images', 'label': '生成组图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'image_size', 'label': '生成尺寸 (Size)', 'type': 'select', 'options': [
                    {'value': '2K', 'text': '2K (默认)'},
                    {'value': '4K', 'text': '4K (超清)'},
                ], 'default': '2K'},
                {'id': 'prompt_aspect_ratio', 'label': '画面比例 (仅追加到提示词)', 'type': 'select', 'options': [
                    {'value': 'none', 'text': '不指定'},
                    {'value': '1:1', 'text': '1:1 (正方形)'},
                    {'value': '3:4', 'text': '3:4 (竖版)'},
                    {'value': '4:3', 'text': '4:3 (横版)'},
                    {'value': '16:9', 'text': '16:9 (横版)'},
                    {'value': '9:16', 'text': '9:16 (竖版)'},
                    {'value': '3:2', 'text': '3:2 (横版)'},
                    {'value': '2:3', 'text': '2:3 (竖版)'},
                    {'value': '21:9', 'text': '21:9 (宽屏)'}
                ], 'default': '9:16'},
                {'id': 'watermark', 'label': '添加官方水印', 'type': 'checkbox', 'default': False}
                # 文档指出 4.5 默认 jpeg 不支持自定义格式，且不支持联网搜索，故在此省略
            ]
        },
        'seedream-4.0-official': {
            'provider': 'volcengine',
            'category': 'multi',
            'endpoint': 'doubao-seedream-4-0-250828',
            'title': 'Seedream 4.0 (官方)',
            'desc': '字节官方 API，支持牺牲部分画质的极速生成模式',
            'params': [
                {'id': 'max_images', 'label': '生成组图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'image_size', 'label': '生成尺寸 (Size)', 'type': 'select', 'options': [
                    {'value': '1K', 'text': '1K (较快)'},
                    {'value': '2K', 'text': '2K (默认)'},
                    {'value': '4K', 'text': '4K (超清)'},
                ], 'default': '2K'},
                {'id': 'prompt_aspect_ratio', 'label': '画面比例 (仅追加到提示词)', 'type': 'select', 'options': [
                    {'value': 'none', 'text': '不指定'},
                    {'value': '1:1', 'text': '1:1 (正方形)'},
                    {'value': '3:4', 'text': '3:4 (竖版)'},
                    {'value': '4:3', 'text': '4:3 (横版)'},
                    {'value': '16:9', 'text': '16:9 (横版)'},
                    {'value': '9:16', 'text': '9:16 (竖版)'},
                    {'value': '3:2', 'text': '3:2 (横版)'},
                    {'value': '2:3', 'text': '2:3 (竖版)'},
                    {'value': '21:9', 'text': '21:9 (宽屏)'}
                ], 'default': '9:16'},
                {'id': 'optimize_prompt_mode', 'label': '生成模式', 'type': 'select', 'options': [
                    {'value': 'standard', 'text': '标准模式 (重画质)'},
                    {'value': 'fast', 'text': '极速模式 (重速度)'}
                ], 'default': 'standard'},
                {'id': 'watermark', 'label': '添加官方水印', 'type': 'checkbox', 'default': False}
            ]
        },
        'seedream-5.0-lite-edit-fal': {
            'provider': 'fal_ai',
            'category': 'multi',
            'endpoint': 'fal-ai/bytedance/seedream/v5/lite/edit',
            'title': 'Seedream 5.0 Lite (Fal)',
            'desc': '支持最多10张图的复杂特征融合与编辑',
            'params': [
                {'id': 'num_images', 'label': '生成图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'max_images', 'label': '最大生成图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'image_size', 'label': '生成尺寸 (Size)', 'type': 'select', 'options': [
                    {'value': 'auto_2K', 'text': '2K'},
                    {'value': 'auto_3K', 'text': '3K'},
                    {'value': 'portrait_16_9', 'text': '竖版 9:16'},
                    {'value': 'portrait_4_3', 'text': '竖版 3:4'},
                    {'value': 'landscape_16_9', 'text': '横版 16:9'},
                    {'value': 'landscape_4_3', 'text': '横版 4:3'},
                    {'value': 'landscape_16_9', 'text': '横版 16:9'},
                    {'value': 'square_hd', 'text': '1:1 正方形 HD'},
                    {'value': 'square', 'text': '1:1 正方形'}
                ], 'default': 'auto_2K'},
                {'id': 'enable_safety_checker', 'label': '启用安全检查', 'type': 'checkbox', 'default': False}

            ]
        },
        'seedream-4.5-edit-fal': {
            'provider': 'fal_ai',
            'category': 'multi',
            'endpoint': 'fal-ai/bytedance/seedream/v4.5/edit',
            'title': 'Seedream 4.5 (Fal)',
            'desc': '支持最多10张图的复杂特征融合与编辑',
            'params': [
                {'id': 'num_images', 'label': '生成图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'max_images', 'label': '最大生成图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'image_size', 'label': '生成尺寸 (Size)', 'type': 'select', 'options': [
                    {'value': 'auto_2K', 'text': '2K'},
                    {'value': 'auto_4K', 'text': '4K'},
                    {'value': 'portrait_16_9', 'text': '竖版 9:16'},
                    {'value': 'portrait_4_3', 'text': '竖版 3:4'},
                    {'value': 'landscape_16_9', 'text': '横版 16:9'},
                    {'value': 'landscape_4_3', 'text': '横版 4:3'},
                    {'value': 'landscape_16_9', 'text': '横版 16:9'},
                    {'value': 'square_hd', 'text': '1:1 正方形 HD'},
                    {'value': 'square', 'text': '1:1 正方形'}
                ], 'default': 'auto_2K'},
                {'id': 'enable_safety_checker', 'label': '启用安全检查', 'type': 'checkbox', 'default': False}

            ]
        },
        'gemini-3-pro-image-preview': {
            'provider': 'google_ai',
            'category': 'multi',  # 支持多达 14 张参考图
            'endpoint': 'gemini-3-pro-image-preview',
            'title': 'Nano Banana Pro (官方)',
            'desc': '专为专业资产生产设计，默认开启深度思考(Thinking)，支持最高4K画质与复杂语义渲染',
            'params': [
                {'id': 'num_images', 'label': '生成数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'aspect_ratio', 'label': '画幅比例', 'type': 'select', 'options': [
                    {'value': '1:1', 'text': '1:1 (正方形)'},
                    {'value': '3:4', 'text': '3:4 (竖版)'},
                    {'value': '4:3', 'text': '4:3 (横版)'},
                    {'value': '9:16', 'text': '9:16 (竖版)'},
                    {'value': '16:9', 'text': '16:9 (横版)'},
                    {'value': '3:2', 'text': '3:2 (横版)'},
                    {'value': '2:3', 'text': '2:3 (竖版)'},
                    {'value': '5:4', 'text': '5:4 (横版)'},
                    {'value': '4:5', 'text': '4:5 (竖版)'},
                    {'value': '21:9', 'text': '21:9 (宽屏)'}
                ], 'default': '9:16'},
                {'id': 'resolution', 'label': '生成分辨率 (Image Size)', 'type': 'select', 'options': [
                    {'value': '1K', 'text': '1K (1024px)'},
                    {'value': '2K', 'text': '2K (高清)'},
                    {'value': '4K', 'text': '4K (极致原画)'}
                ], 'default': '4K'},
                {'id': 'enable_web_search', 'label': '启用 Google 联网搜索', 'type': 'checkbox', 'default': False, 'help_text': '开启后，可让模型根据最新资讯、天气或搜到的图片来作为生成依据。'}
            ]
        },
        'gemini-2.5-flash-image': {
            'provider': 'google_ai',
            'category': 'multi', # 官方建议最多 3 张参考图
            'endpoint': 'gemini-2.5-flash-image',
            'title': 'Nano Banana Flash (官方)',
            'desc': '主打极速生成，固定 1K 分辨率，专为高吞吐、低延迟任务优化',
            'params': [
                {'id': 'num_images', 'label': '生成数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'aspect_ratio', 'label': '画幅比例', 'type': 'select', 'options': [
                    {'value': '1:1', 'text': '1:1 (正方形)'},
                    {'value': '3:4', 'text': '3:4 (竖版)'},
                    {'value': '4:3', 'text': '4:3 (横版)'},
                    {'value': '9:16', 'text': '9:16 (竖版)'},
                    {'value': '16:9', 'text': '16:9 (横版)'},
                    {'value': '3:2', 'text': '3:2 (横版)'},
                    {'value': '2:3', 'text': '2:3 (竖版)'},
                    {'value': '5:4', 'text': '5:4 (横版)'},
                    {'value': '4:5', 'text': '4:5 (竖版)'},
                    {'value': '21:9', 'text': '21:9 (宽屏)'}
                ], 'default': '9:16'}
                # 注意：2.5 Flash 仅支持 1024px，因此不暴露 resolution 选择下拉框
                # 注意：2.5 Flash 不支持 thinking_level 控制
            ]
        },
        'gemini-3.1-flash-image-preview': {
            'provider': 'google_ai',
            'category': 'multi',  # 改为 multi，因为它原生支持多达 14 张垫图
            'endpoint': 'gemini-3.1-flash-image-preview',
            'title': 'Nano Banana 2 (官方)',
            'desc': '支持最高 4K 画质、多图融合、联网搜索及深度推理的终极生图模型',
            'params': [
                {'id': 'aspect_ratio', 'label': '画幅比例', 'type': 'select', 'options': [
                    {'value': '1:1', 'text': '1:1 (正方形)'},
                    {'value': '3:4', 'text': '3:4 (竖版)'},
                    {'value': '4:3', 'text': '4:3 (横版)'},
                    {'value': '9:16', 'text': '9:16 (竖版)'},
                    {'value': '16:9', 'text': '16:9 (横版)'},
                    {'value': '21:9', 'text': '21:9 (宽屏)'}
                ], 'default': '9:16'},
                {'id': 'resolution', 'label': '生成分辨率 (Image Size)', 'type': 'select', 'options': [
                    {'value': '1K', 'text': '1K (极速)'},
                    {'value': '2K', 'text': '2K (高清)'},
                    {'value': '4K', 'text': '4K (原画)'}
                ], 'default': '4K'},
                {'id': 'thinking_level', 'label': '模型思考深度', 'type': 'select', 'options': [
                    {'value': 'minimal', 'text': 'Minimal (常规速度)'},
                    {'value': 'High', 'text': 'High (深度构图与逻辑分析)'}
                ], 'default': 'minimal', 'help_text': '选择 High 会增加生成时间，但在处理复杂提示词（如多重光影、精准文字渲染、复杂的空间位置关系）时效果更好。'},
                {'id': 'enable_web_search', 'label': '启用 Google 联网搜索', 'type': 'checkbox', 'default': False, 'help_text': '开启后，可让模型根据最新资讯、天气或搜到的图片来作为生成依据。'}
            ]
        },
        'nano-banana-2-edit-fal': {
            'provider': 'fal_ai',
            'category': 'multi',
            'endpoint': 'fal-ai/nano-banana-2/edit',
            'title': 'Nano Banana 2(Fal)',
            'desc': '支持多图融合，适合创意编辑场景',
            'params': [
                {'id': 'num_images', 'label': '生成图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'aspect_ratio', 'label': '画幅比例', 'type': 'select', 'options': [
                    {'value': 'auto', 'text': '智能随机'},
                    {'value': '21:9', 'text': '21:9 (横版)'},
                    {'value': '16:9', 'text': '16:9 (横版)'},
                    {'value': '3:2', 'text': '3:2 (横版)'},
                    {'value': '4:3', 'text': '4:3 (横版)'},
                    {'value': '5:4', 'text': '5:4 (横版)'},
                    {'value': '1:1', 'text': '1:1 (正方)'},
                    {'value': '4:5', 'text': '4:5 (竖版)'},
                    {'value': '3:4', 'text': '3:4 (竖版)'},
                    {'value': '2:3', 'text': '2:3 (竖版)'},
                    {'value': '9:16', 'text': '9:16 (竖版)'},
                ], 'default': '9:16'},
                {'id': 'output_format', 'label': '输出格式', 'type': 'select', 'options': [
                    {'value': 'png', 'text': 'PNG (默认)'},
                    {'value': 'jpeg', 'text': 'jpeg'}
                ], 'default': 'png'},
                {'id': 'safety_tolerance', 'label': '安全检查严格度', 'type': 'range', 
                	'min': 1, 
                	'max': 6, 
                	'step': 1, 
                	'default': 6,
                	'help_text': "数值越低越严格，过低可能导致过度过滤"
                },
                {'id': 'resolution', 'label': '生成分辨率', 
                	'type': 'select', 
                	'options': [
                    	{'value': "0.5K", "text": "0.5K"},
                    	{'value': "1K", "text": "1K"},
                    	{'value': "2K", "text": "2K"},
                        {'value': "4K", "text": "4K"},
                	], 
                	'default': "1K"
                },
                # {'id':'limit_generations','label':'限制生成数量','type':'checkbox','default':True,'help_text':'启用后将严格限制生成数量，确保不会超过设定的数量，适合资源有限的环境'},
                {'id':'enable_web_search','label':'启用网络搜索','type':'checkbox','default':False,'help_text':'启用后将启用网络搜索功能，以获取更丰富的提示词内容，可能会增加生成时间，适合需要更丰富语义理解的场景'},

            ]
        },
        'nano-banana-pro-edit-fal': {
            'provider': 'fal_ai',
            'category': 'multi',
            'endpoint': 'fal-ai/nano-banana-pro/edit',
            'title': 'Nano Banana Pro(Fal)',
            'desc': '支持多图融合，适合创意编辑场景',
            'params': [
                {'id': 'num_images', 'label': '生成图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'aspect_ratio', 'label': '画幅比例', 'type': 'select', 'options': [
                    {'value': 'auto', 'text': '智能随机'},
                    {'value': '21:9', 'text': '21:9 (横版)'},
                    {'value': '16:9', 'text': '16:9 (横版)'},
                    {'value': '3:2', 'text': '3:2 (横版)'},
                    {'value': '4:3', 'text': '4:3 (横版)'},
                    {'value': '5:4', 'text': '5:4 (横版)'},
                    {'value': '1:1', 'text': '1:1 (正方)'},
                    {'value': '4:5', 'text': '4:5 (竖版)'},
                    {'value': '3:4', 'text': '3:4 (竖版)'},
                    {'value': '2:3', 'text': '2:3 (竖版)'},
                    {'value': '9:16', 'text': '9:16 (竖版)'},
                ], 'default': '9:16'},
                {'id': 'output_format', 'label': '输出格式', 'type': 'select', 'options': [
                    {'value': 'png', 'text': 'PNG (默认)'},
                    {'value': 'jpeg', 'text': 'jpeg'}
                ], 'default': 'png'},
                {'id': 'safety_tolerance', 'label': '安全检查严格度', 'type': 'range', 
                	'min': 1, 
                	'max': 6, 
                	'step': 1, 
                	'default': 6,
                	'help_text': "数值越低越严格，过低可能导致过度过滤"
                },
                {'id': 'resolution', 'label': '生成分辨率', 
                	'type': 'select', 
                	'options': [
                    	{'value': "0.5K", "text": "0.5K"},
                    	{'value': "1K", "text": "1K"},
                    	{'value': "2K", "text": "2K"},
                        {'value': "4K", "text": "4K"},
                	], 
                	'default': "1K"
                },
                # {'id':'limit_generations','label':'限制生成数量','type':'checkbox','default':True,'help_text':'启用后将严格限制生成数量，确保不会超过设定的数量，适合资源有限的环境'},
                {'id':'enable_web_search','label':'启用网络搜索','type':'checkbox','default':False,'help_text':'启用后将启用网络搜索功能，以获取更丰富的提示词内容，可能会增加生成时间，适合需要更丰富语义理解的场景'},

            ]
        },
    }
}

# ==========================================
# 辅助函数
# ==========================================
def get_tags_bar_data():
    """
    【自愈版】获取标签栏数据：
    自动扫描实际作品中用到的 model_info，如果发现没有注册在 AIModel 表里的模型，自动补齐。
    绝对不会再发生模型标签丢失的问题。
    """
    from django.db.models import Count
    
    # 1. 统计作品表中各模型的使用次数 (以实际作品为准)
    model_stats = PromptGroup.objects.values('model_info').annotate(
        use_count=Count('id')
    ).filter(use_count__gt=0)
    
    final_bar = []
    # 获取目前 AIModel 表里已经注册的名字
    registered_models = list(AIModel.objects.values_list('name', flat=True))
    
    # 2. 构造模型 Tab 数据
    for stat in model_stats:
        m_name = stat['model_info']
        if not m_name: 
            continue
            
        # 【核心修复】：如果发现作品里用到了某个模型，但 AIModel 表里没有，立刻自动注册！
        if m_name not in registered_models:
            AIModel.objects.get_or_create(name=m_name)
            registered_models.append(m_name) # 加入列表，确保下一步能把普通标签里的同名排除掉
            
        final_bar.append({
            'name': m_name,
            'use_count': stat['use_count'],
            'is_model': 1  # 标记为模型，排在首页顶部
        })

    # 3. 获取剩余的普通标签 (排除掉所有的模型名)
    tags = Tag.objects.exclude(name__in=registered_models).annotate(
        use_count=Count('promptgroup')
    ).filter(use_count__gt=0).order_by('-use_count')

    for t in tags:
        final_bar.append({
            'name': t.name,
            'use_count': t.use_count,
            'is_model': 2  # 标记为普通标签，排在侧边栏
        })

    # 4. 排序返回：先按分类(模型在前)，再按使用次数降序
    final_bar.sort(key=lambda x: (x['is_model'], -x['use_count']))
    
    return final_bar

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

def generate_smart_title(prompt_text):
    """
    智能概括标题：优先尝试本地大模型，兜底使用正则截取。
    """
    if not prompt_text:
        return "AI 独立创作"

    # 1. 尝试调用本地大模型 (如果你在 ai_utils 里写了的话)
    try:
        from .ai_utils import generate_title_with_local_llm
        ai_title = generate_title_with_local_llm(prompt_text)
        if ai_title:
            # 【日志提示】：大模型成功
            print(f"✨ [标题生成] 成功使用本地大模型概括: {ai_title}")
            return ai_title
        else:
            print("⚠️ [标题生成] 大模型返回为空，准备降级...")
    except Exception as e:
        # 【日志提示】：大模型异常
        print(f"❌ [标题生成] 大模型调用失败或未加载，原因: {e}")
        pass

    # 2. 降级兜底方案 (正则表达式本地清洗与截取)
    # 【日志提示】：触发兜底
    print(f"🔀 [标题生成] 触发正则兜底机制...")
    clean_text = re.sub(r'--[a-zA-Z0-9\-]+\s+[\d\.]+', '', prompt_text)
    clean_text = re.sub(r'<[^>]+>', '', clean_text)
    
    parts = re.split(r'[,，.。\n;；|]', clean_text)
    parts = [p.strip() for p in parts if p.strip()]

    title = ""
    for part in parts:
        # ====================
        # 修改后：扩充黑名单，过滤掉常见的数量词、镜头词和渲染词
        # ====================
        ignore_pattern = r'^(a|an|the|1girl|1boy|solo|masterpiece|best quality|high quality|highres|ultra-detailed|8k|4k|photorealistic|realistic|3d|cg|render|octane|unreal engine|film grain|lomo|ccd)\s+'
        part = re.sub(ignore_pattern, '', part, flags=re.IGNORECASE).strip()
        
        # 过滤掉纯英文数字的短标签（比如单纯的镜头型号）
        if not part or re.match(r'^[a-zA-Z0-9\-\s]+$', part) and len(part) < 5: 
            continue

        if not title:
            title = part
        else:
            if len(title) + len(part) + 1 <= 28:
                title += f"，{part}"
            else:
                break

    if title:
        title = title[0].upper() + title[1:]
        # 【日志提示】：正则截取成功
        print(f"✅ [标题生成] 正则截取结果: {title}")
        return title

    # 【日志提示】：连正则都没截出来
    print(f"ℹ️ [标题生成] 兜底提取失败，使用默认标题")
    return "AI 独立创作"
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
            Q(model_info__icontains=query) |       # 【新增】支持搜模型
            Q(characters__name__icontains=query) | # 【新增】支持搜人物
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
            Q(group__model_info__icontains=query_text) |       # 【新增】支持搜模型
            Q(group__characters__name__icontains=query_text) | # 【新增】支持搜人物
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
            Q(model_info__icontains=query) |       # 【新增】支持搜模型
            Q(characters__name__icontains=query) | # 【新增】支持搜人物
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
    chars_list = list(group.characters.all()) if hasattr(group, 'characters') else []
    model_name = group.model_info
    if model_name:
        tags_list.sort(key=lambda t: 0 if t.name == model_name else 1)
    # 【检查】：构造混合联想词库 (Tag + Character)
    base_tags = Tag.objects.annotate(usage_count=Count('promptgroup')).order_by('-usage_count', 'name')[:500]
    all_tags = list(base_tags)
    
    try:
        # 再获取人物标签并混入列表
        all_chars = Character.objects.annotate(usage_count=Count('promptgroup')).order_by('-usage_count', 'name')[:200]
        existing_names = {t.name for t in all_tags}
        for c in all_chars:
            if c.name not in existing_names:
                all_tags.append(c) # 只要模型有 .name 属性，前端 datalist 就能正常显示
    except Exception:
        pass
    # all_tags = Tag.objects.annotate(usage_count=Count('promptgroup')).order_by('-usage_count', 'name')[:500]

    siblings_qs = PromptGroup.objects.filter(
        group_id=group.group_id
    ).exclude(pk=group.pk).order_by('-created_at')
    
    siblings = []
    current_prompt = group.prompt_text or ""
    
    for sib in siblings_qs:
        sib_prompt = sib.prompt_text or ""
        sib.diff_html = generate_diff_html(current_prompt, sib_prompt)
        siblings.append(sib)

    # 1. 获取当前卡片的标签 ID 列表
    tag_ids = group.tags.values_list('id', flat=True)

    if not tag_ids:
        related_groups = []
    else:
        # 2. 核心改进逻辑：
        related_groups = PromptGroup.objects.filter(
            tags__id__in=tag_ids                 # 匹配拥有相同标签的作品
        ).exclude(
            group_id=group.group_id              # 排除掉当前作品及其变体系列
        ).annotate(
            same_tag_count=Count('tags')         # 【关键】统计每张候选卡片与当前卡片重合的标签数量
        ).order_by(
            '-same_tag_count',                   # 1. 标签重合越多（越像）的排越前面
            '?'                                  # 2. 在相似度相同时随机打乱（打破“永远一样”的僵局）
        ).distinct()[:4]
    
    tags_bar = get_tags_bar_data()

    return render(request, 'gallery/detail.html', {
        'group': group,
        'sorted_tags': tags_list,
        'chars_list': chars_list,
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

        # 【新增】：智能概括上传页的标题
        if title == '未命名组' and prompt_text:
            title = generate_smart_title(prompt_text)
            print(f"DEBUG: 上传页生成了智能标题 -> {title}")
        
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
        
        # 【新增】：常规上传的模型标签排他性处理
        # if model_name_str:
        #     m_tag, _ = Tag.objects.get_or_create(name=model_name_str)
        #     group.tags.add(m_tag)
            
        #     all_model_names = list(AIModel.objects.values_list('name', flat=True))
        #     for tag in group.tags.all():
        #         if tag.name in all_model_names and tag.name != model_name_str:
        #             group.tags.remove(tag)

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
        
        # 【智能分流逻辑】
        # 1. 先检查全库是否已有该人物
        if hasattr(group, 'characters'):
            from .models import Character
            if Character.objects.filter(name__iexact=tag_name).exists():
                char = Character.objects.get(name__iexact=tag_name)
                # 纠正大小写体验
                if char.name != tag_name:
                    char.name = tag_name
                    char.save()
                group.characters.add(char)
                return JsonResponse({'status': 'success', 'tag_id': char.id, 'tag_name': char.name, 'tag_type': 'character'})
        
        # 2. 如果不是人物，则作为普通标签处理
        tag, created = Tag.objects.get_or_create(name=tag_name)
        group.tags.add(tag)
        return JsonResponse({'status': 'success', 'tag_id': tag.id, 'tag_name': tag.name, 'tag_type': 'tag'})
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})


@require_POST
def remove_tag_from_group(request, pk):
    group = get_object_or_404(PromptGroup, pk=pk)
    try:
        data = json.loads(request.body)
        tag_id = data.get('tag_id')
        tag_type = data.get('tag_type', 'tag') # 接收前端传来的类型，默认为 tag
        
        # 【智能分流删除逻辑】
        if tag_type == 'character' and hasattr(group, 'characters'):
            from .models import Character
            char = get_object_or_404(Character, pk=tag_id)
            group.characters.remove(char)
        else:
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
            Q(prompt_text_zh__icontains=query) |
            Q(model_info__icontains=query) |       # 加上模型搜索
            Q(characters__name__icontains=query) | # 加上人物搜索
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

@require_POST
def add_ai_model(request):
    try:
        data = json.loads(request.body)
        name = data.get('name', '').strip()
        if not name:
             return JsonResponse({'status': 'error', 'message': '模型名称不能为空'})
        
        # 创建 AIModel (显示在侧边栏/顶部)
        AIModel.objects.get_or_create(name=name)
        # 同时创建 Tag (用于搜索关联)
        Tag.objects.get_or_create(name=name)
        
        return JsonResponse({'status': 'success'})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})
    
@require_GET
def create_view(request):
    """渲染 AI 独立创作工作室页面，并将配置和初始数据注入前端"""
    template_id = request.GET.get('template_id')
    prompt_type = request.GET.get('prompt_type', 'positive')
    
    initial_data = {'prompt': '', 'tags': [], 'characters': [], 'reference_urls': []}
    
    if template_id:
        try:
            source_group = PromptGroup.objects.get(pk=template_id)
            
            selected_prompt = ""
            if prompt_type == 'positive' and source_group.prompt_text:
                selected_prompt = source_group.prompt_text
            elif prompt_type == 'positive_zh' and source_group.prompt_text_zh:
                selected_prompt = source_group.prompt_text_zh
            elif prompt_type == 'negative' and source_group.negative_prompt:
                selected_prompt = source_group.negative_prompt
            else:
                selected_prompt = source_group.prompt_text or source_group.prompt_text_zh or ""
                
            tags = [tag.name for tag in source_group.tags.all()]

            chars = []
            if hasattr(source_group, 'characters'):
                chars = [char.name for char in source_group.characters.all()]
            
            ref_urls = [ref.image.url for ref in source_group.references.all() if ref.image]
            if not ref_urls:
                first_img = source_group.images.first()
                if first_img and first_img.image:
                    ref_urls.append(first_img.image.url)
                    
            initial_data = {
                'prompt': selected_prompt, 
                'tags': tags, 
                'characters': chars,
                'reference_urls': ref_urls,
                'model_info': source_group.model_info  
            }
        except PromptGroup.DoesNotExist:
            pass

    # 【新增】获取全库所有已有的标签名称列表
    all_tags = list(Tag.objects.values_list('name', flat=True).distinct())
    all_chars = []
    try:
        from .models import Character
        all_chars = list(Character.objects.values_list('name', flat=True).distinct())
    except Exception:
        pass

    return render(request, 'gallery/create.html', {
        'ai_config_json': json.dumps(AI_STUDIO_CONFIG),
        'initial_data_json': json.dumps(initial_data),
        'all_tags_json': json.dumps(all_tags),
        'all_chars_json': json.dumps(all_chars),
    })

@csrf_exempt
@require_POST
def api_generate_and_download(request):
    try:
        prompt = request.POST.get('prompt', '').strip()
        model_choice = request.POST.get('model_choice')
        base_image_files = request.FILES.getlist('base_images') 

        if not prompt:
            return JsonResponse({'status': 'error', 'message': '提示词不能为空'})
            
        model_config = AI_STUDIO_CONFIG['models'].get(model_choice)
        if not model_config:
            return JsonResponse({'status': 'error', 'message': f'未知的模型: {model_choice}'})

        category_id = model_config['category']
        
        # 1. 获取默认参数
        api_args = {}
        for param in model_config.get('params', []):
            api_args[param['id']] = param['default']
        api_args['prompt'] = prompt

        # 2. 动态参数智能覆写与类型转换
        for param in model_config.get('params', []):
            key = param['id']
            if key in request.POST:
                val = request.POST.get(key)
                default_val = param['default']
                try:
                    if isinstance(default_val, bool):
                        api_args[key] = str(val).lower() in ['true', '1', 'yes', 'on']
                    elif isinstance(default_val, int):
                        api_args[key] = int(val)
                    elif isinstance(default_val, float):
                        api_args[key] = float(val)
                    else:
                        api_args[key] = val
                except ValueError:
                    pass 

        # 3. 获取上传图片列表 (控制最大张数)
        files_to_upload = []
        img_max = next((cat['img_max'] for cat in AI_STUDIO_CONFIG['categories'] if cat['id'] == category_id), 0)
        if img_max > 0:
            if not base_image_files:
                return JsonResponse({'status': 'error', 'message': '该模型需要至少一张参考图片'})
            files_to_upload = base_image_files[:img_max]

        # ==========================================
        # 核心修改点：使用适配器模式请求云端，解耦第三方 SDK
        # ==========================================
        provider_name = model_config.get('provider', 'fal_ai')
        provider = get_ai_provider(provider_name)
        
        print(f"调用通道: {provider_name} | 模型: {model_choice} | 参数: {api_args}")
        
        try:
            # 获取统一格式的图片 URL 列表
            generated_urls = provider.generate(model_config, api_args, files_to_upload)
        except Exception as e:
            error_str = str(e)
            # 针对火山引擎敏感内容拦截的专项友好提示
            if 'OutputImageSensitiveContentDetected' in error_str:
                friendly_msg = '生成失败：触发了官方安全审核机制。生成的画面或参考垫图可能存在敏感特征，请尝试修改服装、姿态等描述词，或更换垫图！'
                return JsonResponse({'status': 'error', 'message': friendly_msg})
            elif 'InputSensitiveContentDetected' in error_str:
                friendly_msg = '生成失败：输入的提示词触发了安全违规词库，请检查并修改提示词。'
                return JsonResponse({'status': 'error', 'message': friendly_msg})
            else:
                return JsonResponse({'status': 'error', 'message': f'云端接口调用失败: {error_str}'})

        if not generated_urls:
            return JsonResponse({'status': 'error', 'message': '云端未返回任何图片'})

        # ==========================================
        # 5. 下载所有生成的图片 (业务逻辑保持不变)
        # ==========================================
        downloads_dir = r"G:\CommonData\图片\Imagegeneration_API" # 根据你的配置
        os.makedirs(downloads_dir, exist_ok=True) 
        
        base_timestamp = int(time.time())
        saved_paths = []
        final_urls = []

        print(f"云端共生成了 {len(generated_urls)} 张图片，开始处理...")

        for idx, img_url in enumerate(generated_urls):
            # 【核心修复】：增加判空保护，跳过生成失败的空 URL
            if not img_url:
                print(f"⚠️ 第 {idx+1} 张图片云端未返回 URL，已跳过。")
                continue
                
            final_urls.append(img_url)
            file_name = f"Gen_{model_choice}_{base_timestamp}_{idx+1}.jpg" 
            file_path = os.path.join(downloads_dir, file_name)
            
            try:
                if img_url.startswith('data:image'):
                    # 【新增】如果是 Google 传回来的 Base64 数据，直接解码存入硬盘，无需发起网络请求
                    header, encoded = img_url.split(",", 1)
                    with open(file_path, 'wb') as f:
                        f.write(base64.b64decode(encoded))
                    saved_paths.append(file_path)
                else:
                    # 【保留】如果是 Fal/火山 传回来的普通公网 URL，正常使用 requests 下载
                    img_resp = requests.get(img_url, verify=False, timeout=60)
                    if img_resp.status_code == 200:
                        with open(file_path, 'wb') as f:
                            f.write(img_resp.content)
                        saved_paths.append(file_path)
            except Exception as e:
                print(f"处理第 {idx+1} 张图片失败: {e}")

        return JsonResponse({
            'status': 'success',
            'message': f'成功生成并下载了 {len(saved_paths)} 张图片！',
            'image_urls': final_urls,
            'saved_paths': saved_paths
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
    
@csrf_exempt
@require_POST
def api_publish_studio_creation(request):
    """处理从 AI 创作室一键发布作品卡片的请求"""
    try:
        prompt = request.POST.get('prompt', '').strip()
        model_info = request.POST.get('model_info', '').strip()
        title = request.POST.get('title', '').strip()
        
        # 【关键修正】：确保在这里一起获取 tags_str 和 chars_str
        tags_str = request.POST.get('tags', '').strip()
        chars_str = request.POST.get('characters', '').strip() 
        
        saved_paths = request.POST.getlist('saved_paths') 
        
        if not saved_paths:
            return JsonResponse({'status': 'error', 'message': '没有找到生成的图片路径'})

        # 1. 创建 PromptGroup (智能概括 Prompt 生成卡片标题)
        if not title:
            title = generate_smart_title(prompt)
            print(f"DEBUG: 创作室生成了智能标题 -> {title}")
            
        group = PromptGroup.objects.create(
            title=title,
            prompt_text=prompt,
            model_info=model_info
        )
        
        # 2. 保存普通标签 (单纯保存，不再有智能分流)
        if tags_str:
            for tag_name in tags_str.replace('，', ',').split(','):
                t_name = tag_name.strip()
                if t_name:
                    tag_obj, _ = Tag.objects.get_or_create(name=t_name)
                    group.tags.add(tag_obj)

        # 3. 独立保存人物标签
        if chars_str:
            try:
                from .models import Character
                for char_name in chars_str.replace('，', ',').split(','):
                    c_name = char_name.strip()
                    if c_name:
                        char_obj, _ = Character.objects.get_or_create(name=c_name)
                        group.characters.add(char_obj)
            except Exception as e:
                print(f"人物保存异常: {e}")
        
        # 4. 将本地成图文件读取并存入 Django 的 ImageItem (绑定到组)
        created_image_ids = []
        for path in saved_paths:
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    file_content = ContentFile(f.read())
                    file_name = os.path.basename(path)
                    img_item = ImageItem(group=group)
                    img_item.image.save(file_name, file_content, save=True)
                    created_image_ids.append(img_item.id)
        
        # 5. 如果用户上传了参考图，一并存为参考图
        ref_files = request.FILES.getlist('references')
        for rf in ref_files:
            ReferenceItem.objects.create(group=group, image=rf)
        
        # 6. 触发后台处理生成缩略图等
        if created_image_ids:
            # 引入 trigger_background_processing (如果你在文件顶部没引入，这里做个保险)
            from .services import trigger_background_processing
            trigger_background_processing(created_image_ids)
            
        return JsonResponse({'status': 'success', 'group_id': group.id, 'message': '发布成功！'})
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)

@csrf_exempt
@require_POST
def api_get_similar_groups_by_prompt(request):
    """根据前端传来的 Prompt 文本，计算全库相似度并返回排序后的作品列表 (包含所有系列的历史版本)"""
    try:
        data = json.loads(request.body)
        prompt_text = data.get('prompt', '').strip().lower()
        
        candidates = PromptGroup.objects.all().order_by('-id')[:2000]
        recommendations = []
        
        for other in candidates:
            other_content = (other.prompt_text or "").strip().lower()
            if len(prompt_text) > 0 and len(other_content) > 0:
                ratio = difflib.SequenceMatcher(None, prompt_text, other_content).ratio()
            elif len(prompt_text) == 0:
                ratio = 0.0 
            else:
                continue
            recommendations.append((ratio, other.id, other))
            
        recommendations.sort(key=lambda x: (x[0], x[1]), reverse=True)
        top_recs = recommendations[:15]
        
        results = []
        for ratio, group_id, group in top_recs:
            cover_url = ""
            cover_img = group.cover_image
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
            
            # 【重点新增】：提取人物标签列表
            chars_list = []
            if hasattr(group, 'characters'):
                chars_list = [char.name for char in group.characters.all()]
                     
            results.append({
                'id': group.id,
                'title': group.title,
                'prompt_text': group.prompt_text[:100] + '...' if group.prompt_text and len(group.prompt_text)>100 else (group.prompt_text or '无提示词'),
                'cover_url': cover_url,
                'similarity': f"{int(ratio*100)}%" if len(prompt_text) > 0 else "-",
                'model_info': group.model_info or "无模型",
                'characters': chars_list # 【重点新增】：传给前端
            })
            
        return JsonResponse({'status': 'success', 'results': results})
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})

@csrf_exempt
@require_POST
def api_append_to_existing_group(request):
    """将生成的本地图片追加到现有的 PromptGroup 中"""
    try:
        group_id = request.POST.get('group_id')
        saved_paths = request.POST.getlist('saved_paths')
        
        if not group_id or not saved_paths:
            return JsonResponse({'status': 'error', 'message': '参数缺失'})
            
        group = PromptGroup.objects.get(pk=group_id)
        created_image_ids = []
        
        for path in saved_paths:
            if os.path.exists(path):
                with open(path, 'rb') as f:
                    file_content = ContentFile(f.read())
                    file_name = os.path.basename(path)
                    img_item = ImageItem(group=group)
                    img_item.image.save(file_name, file_content, save=True)
                    created_image_ids.append(img_item.id)
                    
        # 触发后台处理（生成特征向量、缩略图等）
        if created_image_ids:
            from .services import trigger_background_processing
            trigger_background_processing(created_image_ids)
            
        return JsonResponse({'status': 'success', 'group_id': group.id, 'message': '成功追加到该作品！'})
    except PromptGroup.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': '目标作品组不存在'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)})
    
@require_POST
def edit_model_api(request):
    """处理前端修改模型标签名称的请求（终极容错与脏数据清理版）"""
    try:
        data = json.loads(request.body)
        old_name = data.get('old_name', '').strip()
        new_name = data.get('new_name', '').strip()

        if not old_name or not new_name:
            return JsonResponse({'status': 'error', 'message': '标签名称不能为空'})

        if old_name == new_name:
            return JsonResponse({'status': 'success', 'message': '名称未改变'})

        with transaction.atomic(): 
            # ==========================================
            # 1. 安全获取或创建新标签 (免疫 MultipleObjectsReturned)
            # ==========================================
            new_tags = list(Tag.objects.filter(name__iexact=new_name))
            if new_tags:
                new_tag = new_tags[0] # 如果有多个同名新标签，选第一个当“老大”
                # 如果老大名字大小写跟用户输入的不完全一致，纠正它
                if new_tag.name != new_name:
                    new_tag.name = new_name
                    new_tag.save()
            else:
                new_tag = Tag.objects.create(name=new_name)

            # ==========================================
            # 2. 找到所有旧标签（包括重复的脏数据），全部合并到老大身上
            # ==========================================
            old_tags = list(Tag.objects.filter(name__iexact=old_name))
            
            for old_tag in old_tags:
                if old_tag.id != new_tag.id:
                    # 获取使用了这个旧标签的所有画作组
                    groups_with_old_tag = old_tag.promptgroup_set.all()
                    for group in groups_with_old_tag:
                        group.tags.add(new_tag)    # 绑上新标签老大
                        group.tags.remove(old_tag) # 解绑旧标签
                    
                    # 榨干利用价值后，把这个旧标签（或重复的脏标签）无情删除
                    old_tag.delete()

            # ==========================================
            # 3. 处理 AIModel 表，保证顶部的 Tab 栏更新
            # ==========================================
            old_ai_models = AIModel.objects.filter(name__iexact=old_name)
            old_ai_models.delete() # 删掉所有旧的 Tab 名
            
            # 确保新名字被注册到 AIModel 表中 (使用 filter_first 逻辑防报错)
            if not AIModel.objects.filter(name__iexact=new_name).exists():
                AIModel.objects.create(name=new_name)

            # ==========================================
            # 4. 同步更新纯文本字段 model_info
            # ==========================================
            groups_to_update = PromptGroup.objects.filter(model_info__iexact=old_name)
            updated_count = groups_to_update.update(model_info=new_name)

        return JsonResponse({
            'status': 'success', 
            'message': f'重命名成功！已清理重复脏数据，并同步了 {updated_count} 张卡片。'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)})

@csrf_exempt
@require_POST
def api_generate_title(request):
    """前端异步请求智能标题接口"""
    try:
        data = json.loads(request.body)
        prompt = data.get('prompt', '').strip()
        
        if not prompt:
            return JsonResponse({'status': 'success', 'title': 'AI 独立创作'})
            
        # 调用现成的本地 LLM 标题概括函数
        title = generate_smart_title(prompt)
        return JsonResponse({'status': 'success', 'title': title})
        
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': str(e)})