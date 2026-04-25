import os
import math
import time
import difflib
import uuid
import json
import re
import shutil
import hashlib
import mimetypes
import fal_client
import requests
import base64
import numpy as np
from rapidfuzz import fuzz
import warnings 
import subprocess
import meilisearch
from collections import defaultdict
from urllib3.exceptions import InsecureRequestWarning 
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.conf import settings
from django.http import JsonResponse
from django.urls import reverse
from django.db.models import Q, Count, Case, When, IntegerField, Max, Prefetch
from django.db import transaction
from django.core.files.base import ContentFile
from django.core.files.images import get_image_dimensions
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.paginator import Paginator
from django.views.decorators.http import require_GET, require_POST
from django.core.cache import cache
from django.template.loader import render_to_string
from django.views.decorators.csrf import csrf_exempt
from .models import ImageItem, PromptGroup, Tag, AIModel, ReferenceItem, Character, PROVIDER_CHOICES, GPTImageConversation, GPTImageConversationTurn, GPT_IMAGE_CONVERSATION_SOURCE_CHOICES
from .forms import PromptGroupForm
from .ai_utils import search_similar_images, generate_title_with_local_llm
from .ai_providers import get_ai_provider
from .prompt_mediation import mediate_gpt_image_prompt
from rapidfuzz import process, fuzz

# === 引入 Service 层 ===
from .services import (
    get_temp_dir, 
    calculate_file_hash, 
    trigger_background_processing,
    confirm_upload_images
)

DETAIL_SORT_MODES = {'similar', 'latest'}
DETAIL_RATIO_FILTERS = {'all', 'landscape', 'portrait', 'square'}
HIDDEN_MODEL_SUGGESTION_NAMES = {'GPT Image 2 官方'}
LEGACY_MODEL_ALIAS_MAP = {
    'GPT Image 2 官方': 'GPT Image 2',
}
ADAPTIVE_PROMPT_OPTIMIZATION_LEVELS = ('off', 'balanced', 'enhanced')
ADAPTIVE_PROMPT_OPTIMIZATION_ALIASES = {
    'conservative': 'balanced',
    'faithful': 'balanced',
    'visual_rewrite': 'enhanced',
}


def _normalize_detail_sort_mode(value):
    if value in DETAIL_SORT_MODES:
        return value
    return 'similar'


def _normalize_detail_ratio_filter(value):
    if value in DETAIL_RATIO_FILTERS:
        return value
    return 'all'


def _get_visible_model_suggestion_queryset():
    return AIModel.objects.exclude(name__in=HIDDEN_MODEL_SUGGESTION_NAMES)


def _cleanup_legacy_ai_studio_aliases():
    for legacy_name, canonical_name in LEGACY_MODEL_ALIAS_MAP.items():
        if legacy_name == canonical_name:
            continue

        if canonical_name:
            AIModel.objects.get_or_create(name=canonical_name)

        AIModel.objects.filter(name=legacy_name).delete()
        Tag.objects.filter(name=legacy_name).delete()


def _load_feature_vector(item):
    if not item.feature_vector:
        return None

    try:
        vector = np.frombuffer(item.feature_vector, dtype=np.float32)
    except (TypeError, ValueError):
        return None

    if vector.size == 0:
        return None

    norm = np.linalg.norm(vector)
    if not np.isfinite(norm) or norm <= 0:
        return None

    return vector / norm


def _order_images_by_similarity(images):
    if len(images) < 2:
        return list(images)

    vector_entries = []
    trailing_images = []

    for original_index, image in enumerate(images):
        vector = _load_feature_vector(image)
        if vector is None:
            trailing_images.append((original_index, image))
            continue
        vector_entries.append((original_index, image, vector))

    if len(vector_entries) < 2:
        return list(images)

    vectors = np.stack([entry[2] for entry in vector_entries]).astype(np.float32)
    similarity_matrix = vectors @ vectors.T

    remaining = set(range(len(vector_entries)))
    ordered_positions = [0]
    remaining.remove(0)
    current_position = 0

    while remaining:
        next_position = max(
            remaining,
            key=lambda candidate: (
                float(similarity_matrix[current_position, candidate]),
                -vector_entries[candidate][0],
            ),
        )
        ordered_positions.append(next_position)
        remaining.remove(next_position)
        current_position = next_position

    ordered_images = [vector_entries[position][1] for position in ordered_positions]
    ordered_images.extend(image for _, image in trailing_images)
    return ordered_images


def _build_detail_new_images_payload(request, images):
    new_images_data = []
    html_list = []

    for img in images:
        safe_url = img.image.url if img.image else ''
        if not img.is_video:
            _get_detail_ratio_group(img)

        new_images_data.append({
            'id': img.pk,
            'url': img.image.url if img.image else '',
            'isLiked': img.is_liked,
            'is_video': img.is_video,
            'isVideo': img.is_video,
        })

        html = render_to_string('gallery/components/detail_image_card.html', {
            'img': img,
            'force_image_url': safe_url,
        }, request=request)
        html_list.append(html)

    return html_list, new_images_data


def _get_detail_ratio_group(item):
    if getattr(item, 'detail_ratio_group', None):
        return item.detail_ratio_group

    cache_token = item.image_hash or getattr(item.image, 'name', '') or f'image-{item.pk}'
    cache_key = f'detail-ratio-group:{item.pk}:{cache_token}'
    cached_ratio_group = cache.get(cache_key)
    if cached_ratio_group:
        item.detail_ratio_group = cached_ratio_group
        return item.detail_ratio_group

    if not item.image:
        item.detail_ratio_group = 'unknown'
        return item.detail_ratio_group

    try:
        width, height = get_image_dimensions(item.image)
    except Exception:
        width, height = (None, None)

    if not width or not height:
        item.detail_ratio_group = 'unknown'
        return item.detail_ratio_group

    aspect_ratio = width / height
    if aspect_ratio > 1.05:
        item.detail_ratio_group = 'landscape'
    elif aspect_ratio < 0.95:
        item.detail_ratio_group = 'portrait'
    else:
        item.detail_ratio_group = 'square'

    cache.set(cache_key, item.detail_ratio_group, timeout=60 * 60 * 24 * 30)
    return item.detail_ratio_group

# 填写本地 ComfyUI 的启动批处理文件（.bat）绝对路径
COMFYUI_BAT_PATH = r"E:\comfyUI\启动.bat"
# ==========================================
# 终极配置中心 (Single Source of Truth)
# ==========================================
warnings.filterwarnings("ignore", category=InsecureRequestWarning)
AI_STUDIO_CONFIG = {
    # 1. 大类定义
    'categories': [
        # 增加 'img_required': False，标记图片为可选
        {'id': 'multi', 'title': '🟢 多图融合', 'img_max': 10, 'img_required': False, 'img_help': '按住 Ctrl 键可多选垫图 (最多10张)，也可直接文生图'},
        {'id': 't2i', 'title': '🟠 文生图', 'img_max': 0, 'img_required': False, 'img_help': '纯文本模式，无需传图'},
    ],
    # 2. 具体模型定义
    'models': {
        'seedream-5.0-lite-official': {
            'provider': 'volcengine',
            'category': 'multi',
            'visible_in_categories': ['multi', 't2i'],
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
            'visible_in_categories': ['multi', 't2i'],
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
            'visible_in_categories': ['multi', 't2i'],
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
        'seedream-5.0-lite-fal': {
            'provider': 'fal_ai',
            'category': 't2i',
            'endpoint': 'fal-ai/bytedance/seedream/v5/lite/text-to-image',
            'title': 'Seedream 5.0 Lite 文生图 (Fal)',
            'desc': 'Fal 文生图端点，适合高质量文本生图与快速创意探索',
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
                    {'value': 'square_hd', 'text': '1:1 正方形 HD'},
                    {'value': 'square', 'text': '1:1 正方形'}
                ], 'default': 'auto_2K'},
                {'id': 'enable_safety_checker', 'label': '启用安全检查', 'type': 'checkbox', 'default': False}
            ]
        },
        'seedream-4.5-fal': {
            'provider': 'fal_ai',
            'category': 't2i',
            'endpoint': 'fal-ai/bytedance/seedream/v4.5/text-to-image',
            'title': 'Seedream 4.5 文生图 (Fal)',
            'desc': 'Fal 文生图端点，适合高质量纯文本生成',
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
                    {'value': 'square_hd', 'text': '1:1 正方形 HD'},
                    {'value': 'square', 'text': '1:1 正方形'}
                ], 'default': 'auto_2K'},
                {'id': 'enable_safety_checker', 'label': '启用安全检查', 'type': 'checkbox', 'default': False}
            ]
        },
        'seedream-4.0-fal': {
            'provider': 'fal_ai',
            'category': 't2i',
            'endpoint': 'fal-ai/bytedance/seedream/v4/text-to-image',
            'title': 'Seedream 4.0 文生图 (Fal)',
            'desc': 'Fal 文生图端点，适合较快的 Seedream 文本生成',
            'params': [
                {'id': 'num_images', 'label': '生成图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'max_images', 'label': '最大生成图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'image_size', 'label': '生成尺寸 (Size)', 'type': 'select', 'options': [
                    {'value': 'auto_2K', 'text': '2K'},
                    {'value': 'portrait_16_9', 'text': '竖版 9:16'},
                    {'value': 'portrait_4_3', 'text': '竖版 3:4'},
                    {'value': 'landscape_16_9', 'text': '横版 16:9'},
                    {'value': 'landscape_4_3', 'text': '横版 4:3'},
                    {'value': 'square_hd', 'text': '1:1 正方形 HD'},
                    {'value': 'square', 'text': '1:1 正方形'}
                ], 'default': 'auto_2K'},
                {'id': 'enable_safety_checker', 'label': '启用安全检查', 'type': 'checkbox', 'default': False}
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
        'gpt-image-2-edit-fal': {
            'provider': 'fal_ai',
            'category': 'multi',
            'endpoint': 'openai/gpt-image-2/edit',
            'title': 'GPT Image 2 (Fal)',
            'registry_name': 'GPT Image 2',
            'desc': 'OpenAI 最新细粒度图像编辑模型，支持参考图与蒙版局部重绘',
            'requires_base_images': True,
            'base_images_help': '当前模型至少需要 1 张参考图片，支持最多 10 张图联合编辑',
            'max_base_images': 10,
            'custom_size_param': 'image_size',
            'custom_size_format': 'object',
            'supports_mask': True,
            'mask_optional': True,
            'file_params': [
                {
                    'id': 'mask_url',
                    'label': '编辑蒙版',
                    'accept': 'image/*',
                    'required': False,
                    'help_text': '上传黑白蒙版后，仅会编辑蒙版指定区域；不上传则对整张图执行智能编辑。'
                }
            ],
            'params': [
                {'id': 'num_images', 'label': '生成图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'image_size_mode', 'label': '尺寸控制', 'type': 'select', 'options': [
                    {'value': 'auto', 'text': '自动匹配参考图'},
                    {'value': 'custom', 'text': '自定义分辨率'}
                ], 'default': 'custom'},
                {'id': 'aspect_ratio', 'label': '画幅比例', 'type': 'select', 'options': [
                    {'value': '1:1', 'text': '1:1 (正方形)'},
                    {'value': '4:3', 'text': '4:3 (横版)'},
                    {'value': '3:4', 'text': '3:4 (竖版)'},
                    {'value': '16:9', 'text': '16:9 (横版)'},
                    {'value': '9:16', 'text': '9:16 (竖版)'}
                ], 'default': '9:16'},
                {'id': 'resolution', 'label': '目标分辨率', 'type': 'select', 'options': [
                    {'value': '1K', 'text': '1K 级别'},
                    {'value': '2K', 'text': '2K 级别'},
                    {'value': '4K', 'text': '4K 级别'}
                ], 'default': '2K'},
                {'id': 'quality', 'label': '生成质量', 'type': 'select', 'options': [
                    {'value': 'low', 'text': 'Low'},
                    {'value': 'medium', 'text': 'Medium'},
                    {'value': 'high', 'text': 'High'}
                ], 'default': 'medium'},
                {'id': 'prompt_optimization_level', 'label': 'Prompt 优化强度', 'type': 'select', 'options': [
                    {'value': 'off', 'text': '关闭优化'},
                    {'value': 'balanced', 'text': '保真 (默认)'},
                    {'value': 'enhanced', 'text': '增强'}
                ], 'default': 'balanced'},
                {'id': 'output_format', 'label': '输出格式', 'type': 'select', 'options': [
                    {'value': 'png', 'text': 'PNG (默认)'},
                    {'value': 'jpeg', 'text': 'JPEG'},
                    {'value': 'webp', 'text': 'WebP'}
                ], 'default': 'png'}
            ]
        },
        'gpt-image-2-openai': {
            'provider': 'openai',
            'category': 'multi',
            'endpoint': 'gpt-image-2',
            'title': 'GPT Image 2 (官方)',
            'registry_name': 'GPT Image 2',
            'desc': 'OpenAI Images API 通道，支持文生图、参考图编辑与蒙版局部重绘',
            'requires_base_images': False,
            'base_images_help': '可直接文生图，也可上传最多 10 张参考图片进行编辑；如使用蒙版，必须先上传参考图',
            'max_base_images': 10,
            'custom_size_param': 'size',
            'custom_size_format': 'string',
            'supports_mask': True,
            'mask_optional': True,
            'file_params': [
                {
                    'id': 'mask_url',
                    'label': '编辑蒙版',
                    'accept': 'image/*',
                    'required': False,
                    'help_text': '仅在已上传参考图时可用。建议使用透明 PNG 蒙版；若上传普通黑白图，后端会自动补 alpha 通道。'
                }
            ],
            'params': [
                {'id': 'num_images', 'label': '生成图数量', 'type': 'range', 'min': 1, 'max': 4, 'step': 1, 'default': 1},
                {'id': 'image_size_mode', 'label': '尺寸控制', 'type': 'select', 'options': [
                    {'value': 'auto', 'text': '自动匹配最佳尺寸'},
                    {'value': 'custom', 'text': '自定义分辨率'}
                ], 'default': 'custom'},
                {'id': 'aspect_ratio', 'label': '画幅比例', 'type': 'select', 'options': [
                    {'value': '1:1', 'text': '1:1 (正方形)'},
                    {'value': '4:3', 'text': '4:3 (横版)'},
                    {'value': '3:4', 'text': '3:4 (竖版)'},
                    {'value': '16:9', 'text': '16:9 (横版)'},
                    {'value': '9:16', 'text': '9:16 (竖版)'}
                ], 'default': '9:16'},
                {'id': 'resolution', 'label': '目标分辨率', 'type': 'select', 'options': [
                    {'value': '1K', 'text': '1K 级别'},
                    {'value': '2K', 'text': '2K 级别'},
                    {'value': '4K', 'text': '4K 级别'}
                ], 'default': '2K'},
                {'id': 'quality', 'label': '生成质量', 'type': 'select', 'options': [
                    {'value': 'low', 'text': 'Low'},
                    {'value': 'medium', 'text': 'Medium'},
                    {'value': 'high', 'text': 'High'}
                ], 'default': 'medium'},
                {'id': 'prompt_optimization_level', 'label': 'Prompt 优化强度', 'type': 'select', 'options': [
                    {'value': 'off', 'text': '关闭优化'},
                    {'value': 'balanced', 'text': '保真 (默认)'},
                    {'value': 'enhanced', 'text': '增强'}
                ], 'default': 'balanced'},
                {'id': 'output_format', 'label': '输出格式', 'type': 'select', 'options': [
                    {'value': 'png', 'text': 'PNG (默认)'},
                    {'value': 'jpeg', 'text': 'JPEG'},
                    {'value': 'webp', 'text': 'WebP'}
                ], 'default': 'png'},
                {'id': 'moderation', 'label': '内容审核', 'type': 'select', 'options': [
                    {'value': 'auto', 'text': 'Auto (默认)'},
                    {'value': 'low', 'text': 'Low (更宽松)'}
                ], 'default': 'auto'},
                {'id': 'background', 'label': '背景模式', 'type': 'select', 'options': [
                    {'value': 'auto', 'text': 'Auto'},
                    {'value': 'opaque', 'text': 'Opaque'}
                ], 'default': 'auto'}
            ]
        },
    }
}


def _get_ai_studio_registry_name(model_config):
    registry_name = (model_config.get('registry_name') or '').strip()
    if registry_name:
        return registry_name

    raw_title = (model_config.get('title') or '').strip()
    if not raw_title:
        return ''

    return re.sub(r'\s*[\(（].*?[\)）]$', '', raw_title).strip()


def ensure_ai_studio_model_labels_registered():
    _cleanup_legacy_ai_studio_aliases()

    for model_config in AI_STUDIO_CONFIG.get('models', {}).values():
        model_name = _get_ai_studio_registry_name(model_config)
        if not model_name:
            continue
        AIModel.objects.get_or_create(name=model_name)
        Tag.objects.get_or_create(name=model_name)


def _round_to_multiple_of_16(value):
    return max(16, int(round(float(value) / 16.0)) * 16)


def _build_gpt_image_2_custom_size(size_mode, aspect_ratio, resolution, output_format='object'):
    if size_mode != 'custom':
        return 'auto'

    aspect_options = {
        '1:1': (1, 1),
        '4:3': (4, 3),
        '3:4': (3, 4),
        '16:9': (16, 9),
        '9:16': (9, 16),
    }
    target_pixels = {
        '1K': 1024 * 1024,
        '2K': 2048 * 2048,
        '4K': 3840 * 2160,
    }

    ratio = aspect_options.get(aspect_ratio)
    pixel_budget = target_pixels.get(resolution)
    if not ratio or not pixel_budget:
        return 'auto'

    ratio_width, ratio_height = ratio
    width = math.sqrt(pixel_budget * ratio_width / ratio_height)
    height = math.sqrt(pixel_budget * ratio_height / ratio_width)

    width = _round_to_multiple_of_16(width)
    height = _round_to_multiple_of_16(height)

    max_edge = 3840
    max_pixels = 8_294_400
    current_pixels = width * height
    if width > max_edge or height > max_edge or current_pixels > max_pixels:
        scale = min(
            max_edge / width,
            max_edge / height,
            math.sqrt(max_pixels / current_pixels),
        )
        width = _round_to_multiple_of_16(width * scale)
        height = _round_to_multiple_of_16(height * scale)

    if output_format == 'string':
        return f'{width}x{height}'

    return {
        'width': width,
        'height': height,
    }


def _get_ai_studio_model_config(model_choice):
    model_config = AI_STUDIO_CONFIG['models'].get(model_choice)
    if not model_config:
        raise ValueError(f'未知的模型: {model_choice}')
    return model_config


def _is_gpt_image_2_model(model_config):
    return _get_ai_studio_registry_name(model_config) == 'GPT Image 2'


def _normalize_prompt_optimization_level(value, default='balanced'):
    normalized = str(value or '').strip().lower()
    normalized = ADAPTIVE_PROMPT_OPTIMIZATION_ALIASES.get(normalized, normalized)
    if normalized in ADAPTIVE_PROMPT_OPTIMIZATION_LEVELS:
        return normalized
    return default


def _should_use_adaptive_prompt_optimization(mapping, model_config):
    if not _is_gpt_image_2_model(model_config) or not hasattr(mapping, 'get'):
        return False

    raw_value = str(mapping.get('adaptive_prompt_optimization') or '').strip().lower()
    return raw_value in {'1', 'true', 'yes', 'on'}


def _get_next_adaptive_prompt_optimization_level(current_level):
    normalized_level = _normalize_prompt_optimization_level(current_level, default='off')
    try:
        current_index = ADAPTIVE_PROMPT_OPTIMIZATION_LEVELS.index(normalized_level)
    except ValueError:
        return 'balanced'

    next_index = current_index + 1
    if next_index >= len(ADAPTIVE_PROMPT_OPTIMIZATION_LEVELS):
        return ''
    return ADAPTIVE_PROMPT_OPTIMIZATION_LEVELS[next_index]


def _get_prompt_optimization_level(mapping, model_config):
    default_level = 'balanced'
    for param in model_config.get('params', []):
        if param.get('id') == 'prompt_optimization_level':
            default_level = param.get('default', default_level)
            break

    if not hasattr(mapping, 'get'):
        return default_level

    explicit_next_level = mapping.get('next_optimization_level')
    if explicit_next_level:
        return _normalize_prompt_optimization_level(explicit_next_level, default=default_level)

    if _should_use_adaptive_prompt_optimization(mapping, model_config):
        return 'off'

    return _normalize_prompt_optimization_level(mapping.get('prompt_optimization_level') or default_level, default=default_level)


def _mediate_ai_studio_prompt(model_choice, model_config, prompt, mapping, optimization_level=None):
    prompt = str(prompt or '').strip()
    mediation = {
        'original_prompt': prompt,
        'optimized_prompt': prompt,
        'optimization_level': 'balanced',
        'changed': False,
        'applied_rules': [],
        'rewrite_details': [],
        'structured_outline': [],
    }

    if prompt and _is_gpt_image_2_model(model_config):
        mediation = mediate_gpt_image_prompt(
            prompt,
            optimization_level=optimization_level or _get_prompt_optimization_level(mapping, model_config),
        )

    return mediation['optimized_prompt'], mediation


def _build_ai_studio_api_args(mapping, model_config, prompt):
    api_args = {}
    for param in model_config.get('params', []):
        api_args[param['id']] = param['default']
    api_args['prompt'] = prompt

    for param in model_config.get('params', []):
        key = param['id']
        if key not in mapping:
            continue

        value = mapping.get(key)
        default_value = param['default']
        try:
            if isinstance(default_value, bool):
                api_args[key] = str(value).lower() in ['true', '1', 'yes', 'on']
            elif isinstance(default_value, int):
                api_args[key] = int(value)
            elif isinstance(default_value, float):
                api_args[key] = float(value)
            else:
                api_args[key] = value
        except (TypeError, ValueError):
            continue

    custom_size_param = model_config.get('custom_size_param')
    if custom_size_param:
        api_args[custom_size_param] = _build_gpt_image_2_custom_size(
            api_args.get('image_size_mode', 'custom'),
            api_args.get('aspect_ratio', '9:16'),
            api_args.get('resolution', '2K'),
            output_format=model_config.get('custom_size_format', 'object'),
        )
        api_args.pop('image_size_mode', None)
        api_args.pop('aspect_ratio', None)
        api_args.pop('resolution', None)

    return api_args


def _classify_ai_studio_error(error):
    error_str = str(error)
    error_code = str(getattr(error, 'code', '') or '').strip().lower()
    error_type = str(getattr(error, 'error_type', '') or '').strip().lower()
    normalized_error_text = error_str.lower()

    moderation_markers = (
        'outputimagesensitivecontentdetected',
        'inputsensitivecontentdetected',
        'content_policy_violation',
        'safety system',
        'content policy',
        'sensitive content',
        'moderation',
        'safety audit',
        'safety review',
        '安全审核',
        '安全违规词库',
        '安全审查',
        '触发了官方安全审核机制',
        '触发了安全',
        '审核机制',
        'rejected as a result of our safety system',
        'violates our content policy',
    )

    if 'OutputImageSensitiveContentDetected' in error_str:
        return {
            'code': 'output_sensitive_content_detected',
            'message': '生成失败：触发了官方安全审核机制。生成的画面或参考垫图可能存在敏感特征，请尝试修改服装、姿态等描述词，或更换垫图！',
            'is_moderation_failure': True,
        }
    if 'InputSensitiveContentDetected' in error_str:
        return {
            'code': 'input_sensitive_content_detected',
            'message': '生成失败：输入的提示词触发了安全违规词库，请检查并修改提示词。',
            'is_moderation_failure': True,
        }

    if error_code in {'content_policy_violation', 'image_content_policy_violation'} or error_type in {'content_policy_violation'}:
        return {
            'code': error_code or 'content_policy_violation',
            'message': '生成失败：请求触发了官方内容审核策略。你可以保留当前意图，逐级提升 Prompt 优化强度后再试。',
            'is_moderation_failure': True,
        }

    if any(marker in normalized_error_text for marker in moderation_markers):
        return {
            'code': error_code or 'content_moderation_rejected',
            'message': '生成失败：请求触发了官方内容审核策略。你可以保留当前意图，逐级提升 Prompt 优化强度后再试。',
            'is_moderation_failure': True,
        }

    return {
        'code': 'provider_error',
        'message': f'云端接口调用失败: {error_str}',
        'is_moderation_failure': False,
    }


def _normalize_ai_studio_error_message(error):
    return _classify_ai_studio_error(error)['message']


def _save_generated_images(model_choice, generated_urls):
    downloads_dir = r"G:\CommonData\图片\Imagegeneration_API"
    os.makedirs(downloads_dir, exist_ok=True)

    base_timestamp = int(time.time())
    saved_paths = []
    final_urls = []

    print(f"云端共生成了 {len(generated_urls)} 张图片，开始处理...")

    for idx, img_url in enumerate(generated_urls):
        if not img_url:
            print(f"⚠️ 第 {idx+1} 张图片云端未返回 URL，已跳过。")
            continue

        final_urls.append(img_url)
        file_name = f"Gen_{model_choice}_{base_timestamp}_{idx+1}.jpg"
        file_path = os.path.join(downloads_dir, file_name)

        try:
            if img_url.startswith('data:image'):
                _, encoded = img_url.split(',', 1)
                with open(file_path, 'wb') as f:
                    f.write(base64.b64decode(encoded))
                saved_paths.append(file_path)
            else:
                img_resp = requests.get(img_url, verify=False, timeout=60)
                if img_resp.status_code == 200:
                    with open(file_path, 'wb') as f:
                        f.write(img_resp.content)
                    saved_paths.append(file_path)
        except Exception as exc:
            print(f"处理第 {idx+1} 张图片失败: {exc}")

    return final_urls, saved_paths


def _run_ai_studio_generation(model_choice, prompt, mapping, base_image_files=None, extra_files=None):
    if not prompt:
        raise ValueError('提示词不能为空')

    model_config = _get_ai_studio_model_config(model_choice)
    category_id = model_config['category']
    cat_config = next((cat for cat in AI_STUDIO_CONFIG['categories'] if cat['id'] == category_id), {})
    img_max = model_config.get('max_base_images', cat_config.get('img_max', 0))
    img_required = model_config.get('requires_base_images', cat_config.get('img_required', True))

    files_to_upload = list(base_image_files or [])
    if img_max > 0:
        if img_required and not files_to_upload:
            raise ValueError('当前模型至少需要上传一张参考图片')
        if files_to_upload:
            files_to_upload = files_to_upload[:img_max]
    else:
        files_to_upload = []

    normalized_extra_files = {}
    for file_param in model_config.get('file_params', []):
        file_obj = (extra_files or {}).get(file_param['id'])
        if file_obj:
            normalized_extra_files[file_param['id']] = file_obj
            continue
        if file_param.get('required'):
            raise ValueError(f"请上传{file_param.get('label', file_param['id'])}")

    if normalized_extra_files.get('mask_url') and not files_to_upload:
        raise ValueError('使用编辑蒙版前请先上传一张参考图片')

    attempted_optimization_level = _get_prompt_optimization_level(mapping, model_config)
    adaptive_prompt_optimization = _should_use_adaptive_prompt_optimization(mapping, model_config)
    optimized_prompt, prompt_mediation = _mediate_ai_studio_prompt(
        model_choice,
        model_config,
        prompt,
        mapping,
        optimization_level=attempted_optimization_level,
    )
    api_args = _build_ai_studio_api_args(mapping, model_config, optimized_prompt)
    provider_name = model_config.get('provider', 'fal_ai')
    provider = get_ai_provider(provider_name)

    print(f"调用通道: {provider_name} | 模型: {model_choice} | 参数: {api_args}")

    try:
        generated_urls = provider.generate(model_config, api_args, files_to_upload, extra_files=normalized_extra_files)
    except Exception as exc:
        error_info = _classify_ai_studio_error(exc)
        if error_info['is_moderation_failure'] and adaptive_prompt_optimization:
            next_optimization_level = _get_next_adaptive_prompt_optimization_level(attempted_optimization_level)
            return {
                'model_config': model_config,
                'provider_name': provider_name,
                'api_args': api_args,
                'prompt_mediation': prompt_mediation,
                'optimized_prompt': optimized_prompt,
                'image_urls': [],
                'saved_paths': [],
                'failed': True,
                'failure_type': 'moderation',
                'message': error_info['message'],
                'error_code': error_info['code'],
                'attempted_optimization_level': attempted_optimization_level,
                'can_retry_higher': bool(next_optimization_level),
                'next_optimization_level': next_optimization_level,
            }
        raise RuntimeError(error_info['message']) from exc

    if not generated_urls:
        raise RuntimeError('云端未返回任何图片')

    image_urls, saved_paths = _save_generated_images(model_choice, generated_urls)
    return {
        'model_config': model_config,
        'provider_name': provider_name,
        'api_args': api_args,
        'prompt_mediation': prompt_mediation,
        'optimized_prompt': optimized_prompt,
        'image_urls': image_urls,
        'saved_paths': saved_paths,
    }


def _parse_json_object(raw_value, default=None):
    if default is None:
        default = {}
    if not raw_value:
        return default.copy()
    if isinstance(raw_value, dict):
        return raw_value
    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError):
        return default.copy()
    return parsed if isinstance(parsed, dict) else default.copy()


def _build_uploaded_file_from_path(file_path):
    if not file_path or not os.path.exists(file_path):
        raise FileNotFoundError('当前会话的基底图路径不存在，无法继续调整')

    with open(file_path, 'rb') as f:
        content = f.read()

    content_type = mimetypes.guess_type(file_path)[0] or 'image/png'
    return SimpleUploadedFile(os.path.basename(file_path), content, content_type=content_type)


def _build_conversation_base_images(conversation):
    if conversation.active_image_id and conversation.active_image and conversation.active_image.image:
        return [_build_uploaded_file_from_path(conversation.active_image.image.path)]
    if conversation.active_image_path:
        return [_build_uploaded_file_from_path(conversation.active_image_path)]
    if conversation.source_image_id and conversation.source_image and conversation.source_image.image:
        return [_build_uploaded_file_from_path(conversation.source_image.image.path)]
    return []


def _serialize_gpt_image_conversation_turn(turn):
    return {
        'id': turn.id,
        'turn_index': turn.turn_index,
        'instruction': turn.instruction,
        'input_image_id': turn.input_image_id,
        'input_image_path': turn.input_image_path,
        'mask_image_path': turn.mask_image_path,
        'output_image_id': turn.output_image_id,
        'output_image_path': turn.output_image_path,
        'request_payload': turn.request_payload,
        'response_payload': turn.response_payload,
        'created_at': turn.created_at.isoformat(),
    }


def _serialize_gpt_image_conversation(conversation, include_turns=False):
    payload = {
        'id': conversation.id,
        'conversation_id': str(conversation.conversation_id),
        'source_page': conversation.source_page,
        'source_prompt_group_id': conversation.source_prompt_group_id,
        'source_image_id': conversation.source_image_id,
        'active_image_id': conversation.active_image_id,
        'active_image_path': conversation.active_image_path,
        'model_key': conversation.model_key,
        'model_label': conversation.model_label,
        'provider': conversation.provider,
        'initial_prompt': conversation.initial_prompt,
        'last_instruction': conversation.last_instruction,
        'latest_params': conversation.latest_params,
        'created_at': conversation.created_at.isoformat(),
        'updated_at': conversation.updated_at.isoformat(),
    }
    if include_turns:
        payload['turns'] = [_serialize_gpt_image_conversation_turn(turn) for turn in conversation.turns.all()]
    return payload


def _serialize_gpt_image_conversation_summary(conversation):
    turns = list(conversation.turns.all())
    last_turn = turns[-1] if turns else None
    return {
        'id': conversation.id,
        'conversation_id': str(conversation.conversation_id),
        'source_page': conversation.source_page,
        'source_prompt_group_id': conversation.source_prompt_group_id,
        'source_image_id': conversation.source_image_id,
        'active_image_id': conversation.active_image_id,
        'active_image_path': conversation.active_image_path,
        'model_key': conversation.model_key,
        'model_label': conversation.model_label,
        'provider': conversation.provider,
        'initial_prompt': conversation.initial_prompt,
        'last_instruction': conversation.last_instruction,
        'turn_count': len(turns),
        'last_turn_id': last_turn.id if last_turn else None,
        'last_turn_output_path': last_turn.output_image_path if last_turn else '',
        'updated_at': conversation.updated_at.isoformat(),
        'created_at': conversation.created_at.isoformat(),
    }

# ==========================================
# 辅助函数
# ==========================================
def get_tags_bar_data():
    """【缓存优化版】获取标签栏数据"""
    cache_key = 'tags_bar_data_v2'
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data

    ensure_ai_studio_model_labels_registered()

    from django.db.models import Count
    model_stats = PromptGroup.objects.values('model_info').annotate(
        use_count=Count('id')
    ).filter(use_count__gt=0)
    
    final_bar = []
    registered_models = list(AIModel.objects.values_list('name', flat=True))
    
    for stat in model_stats:
        m_name = stat['model_info']
        if not m_name: continue
        if m_name not in registered_models:
            AIModel.objects.get_or_create(name=m_name)
            registered_models.append(m_name)
        final_bar.append({'name': m_name, 'use_count': stat['use_count'], 'is_model': 1})

    tags = Tag.objects.exclude(name__in=registered_models).annotate(
        use_count=Count('promptgroup')
    ).filter(use_count__gt=0).order_by('-use_count')

    for t in tags:
        final_bar.append({'name': t.name, 'use_count': t.use_count, 'is_model': 2})

    final_bar.sort(key=lambda x: (x['is_model'], -x['use_count']))
    
    # 将统计结果缓存 2 分钟，避免每次刷新页面都去扫描全表
    cache.set(cache_key, final_bar, 120)
    return final_bar

def get_cached_char_refs_data():
    """【性能飞跃】提取并缓存人物参考图集，避免详情页/上传页 N+1 循环查询瘫痪"""
    cache_key = "global_char_refs_data_v1"
    cached_data = cache.get(cache_key)
    if cached_data:
        return cached_data
        
    char_refs_data = []
    # 优化点：只查询那些【确实有关联参考图】的人物，过滤掉没用的空人物
    all_chars_for_ref = Character.objects.filter(promptgroup__references__isnull=False).distinct().order_by('-order', 'name')
    
    for char in all_chars_for_ref:
        raw_refs = ReferenceItem.objects.select_related('group').filter(group__characters=char).order_by('-id')
        unique_refs = []
        seen_identifiers = set() 
        
        for ref in raw_refs:
            if not ref.image: continue
            fingerprint = ref.image_hash if ref.image_hash else ref.image.name
            if fingerprint not in seen_identifiers:
                seen_identifiers.add(fingerprint)
                unique_refs.append(ref)
            if len(unique_refs) >= 12: break
            
        if unique_refs:
            char_refs_data.append({'character': char, 'refs': unique_refs})
            
    # 缓存 5 分钟 (300秒)，因为这部分数据不需要毫秒级实时
    cache.set(cache_key, char_refs_data, 300)
    return char_refs_data

def generate_diff_html(base_text, compare_text):
    """
    智能折叠版差异高亮（锚定按钮位置版）：
    按钮永远固定在前5个标签的后面，展开的内容在其后方流式铺开，防止按钮被挤走。
    """
    if base_text is None: base_text = ""
    if compare_text is None: compare_text = ""
    
    def parse_tags_to_dict(text):
        import re
        parts = re.split(r'[,\uff0c\n;|；|。]+', text)
        return {p.strip().lower(): p.strip() for p in parts if p.strip()}

    base_map = parse_tags_to_dict(base_text)
    comp_map = parse_tags_to_dict(compare_text)
    
    base_keys = set(base_map.keys())
    comp_keys = set(comp_map.keys())
    
    added_keys = list(comp_keys - base_keys)
    removed_keys = list(base_keys - comp_keys)
    
    if not added_keys and not removed_keys:
        return '<span class="no-diff">无明显差异</span>'
    
    MAX_VISIBLE = 5
    
    all_changes = []
    for k in added_keys:
        all_changes.append(('add', comp_map[k]))
    for k in removed_keys:
        all_changes.append(('rem', base_map[k]))
        
    visible_parts = []
    hidden_parts = []
    
    for i, (change_type, val) in enumerate(all_changes):
        display_val = (val[:15] + '..') if len(val) > 15 else val
        
        hidden_class = " diff-hidden-tag" if i >= MAX_VISIBLE else ""
        hidden_style = ' style="display:none;"' if i >= MAX_VISIBLE else ""
        
        if change_type == 'add':
            tag_html = (
                f'<span class="diff-tag diff-add{hidden_class}"{hidden_style} title="新增: {val}">'
                f'<i class="bi bi-plus"></i>{display_val}</span>'
            )
        else:
            tag_html = (
                f'<span class="diff-tag diff-rem{hidden_class}"{hidden_style} title="移除: {val}">'
                f'<i class="bi bi-dash"></i>{display_val}</span>'
            )
            
        # 将前5个和剩余的标签分别存入不同的列表
        if i < MAX_VISIBLE:
            visible_parts.append(tag_html)
        else:
            hidden_parts.append(tag_html)
            
    html_parts = []
    # 1. 先放入可见的前5个标签
    html_parts.extend(visible_parts)
    
    # 2. 如果有隐藏标签，将按钮紧贴在第5个标签之后插入
    if hidden_parts:
        hidden_count = len(hidden_parts)
        btn_html = (
            f'<span class="diff-tag diff-toggle-btn" onclick="toggleDiff(event, this)" '
            f'data-hidden-count="{hidden_count}" '
            f'style="background: #f8fafc; border: 1px dashed #cbd5e1; color: #64748b; cursor: pointer; transition: all 0.2s;">'
            f'<i class="bi bi-chevron-down"></i> 展开剩余 {hidden_count} 项</span>'
        )
        html_parts.append(btn_html)        # 【关键】按钮在中间
        html_parts.extend(hidden_parts)    # 【关键】隐藏项在按钮后面
        
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


def normalize_prompt_items(raw_prompts):
    return PromptGroup.normalize_prompts(raw_prompts)


def find_duplicate_prompt_texts(prompt_items):
    seen = {}
    duplicates = []

    for item in prompt_items or []:
        original_text = str((item or {}).get('text', '')).strip()
        if not original_text:
            continue

        normalized_text = re.sub(r'\s+', ' ', original_text).strip().lower()
        if not normalized_text:
            continue

        if normalized_text in seen:
            if seen[normalized_text] not in duplicates:
                duplicates.append(seen[normalized_text])
            if original_text not in duplicates:
                duplicates.append(original_text)
            continue

        seen[normalized_text] = original_text

    return duplicates


def extract_prompt_items_from_mapping(mapping):
    raw_prompts = None

    prompts_json = mapping.get('prompts_json') if hasattr(mapping, 'get') else None
    if prompts_json:
        try:
            raw_prompts = json.loads(prompts_json)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw_prompts = None

    if raw_prompts is None and hasattr(mapping, 'get'):
        direct_prompts = mapping.get('prompts')
        if isinstance(direct_prompts, list):
            raw_prompts = direct_prompts
        elif isinstance(direct_prompts, str) and direct_prompts.strip():
            try:
                raw_prompts = json.loads(direct_prompts)
            except (TypeError, ValueError, json.JSONDecodeError):
                raw_prompts = [direct_prompts]

    if raw_prompts is None and hasattr(mapping, 'getlist'):
        prompt_list = [item for item in mapping.getlist('prompts') if str(item or '').strip()]
        if prompt_list:
            raw_prompts = prompt_list

    prompt_items = normalize_prompt_items(raw_prompts)
    if prompt_items:
        return prompt_items

    return PromptGroup.build_prompts_from_legacy_fields(
        mapping.get('prompt_text', '') if hasattr(mapping, 'get') else '',
        mapping.get('prompt_text_zh', '') if hasattr(mapping, 'get') else '',
        mapping.get('negative_prompt', '') if hasattr(mapping, 'get') else '',
    )


def get_primary_prompt_text(prompt_items):
    if prompt_items:
        return prompt_items[0]['text']
    return ''


def get_prompt_summary_text(group, max_length=100):
    text = group.get_primary_prompt_text() or ''
    if len(text) > max_length:
        return text[:max_length] + '...'
    return text
# ==========================================
# 视图函数
# ==========================================

def home(request):
    ensure_ai_studio_model_labels_registered()
    queryset = PromptGroup.objects.all()
    query = request.GET.get('q')
    filter_type = request.GET.get('filter')
    search_id = request.GET.get('search_id')
    
    f_liked = request.GET.get('f_liked')
    f_video = request.GET.get('f_video')
    f_multi = request.GET.get('f_multi')
    f_models = request.GET.getlist('f_model')  # 允许同名多个参数 (多选)
    f_chars = request.GET.getlist('f_char')
    f_tags = request.GET.getlist('f_tag')
    # === 处理以图搜图提交 (POST) -> 转为 GET ===
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

    # === 处理以图搜图结果展示 (GET) ===
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
        try:
            # 尝试向 Meilisearch 发起毫秒级搜索 (填入你的 Master Key)
            client = meilisearch.Client('http://127.0.0.1:7700', 'dq49aaqs-RYHbIfKGMOFJRrfco3jP-0Ubj4gcX9caBc')
            search_res = client.index('prompts').search(query, {
                'limit': 100  # 获取最相关的前 100 条
            })
            
            hit_ids = [hit['id'] for hit in search_res['hits']]
            
            if hit_ids:
                # 保持 Meilisearch 给出的智能排序顺序
                preserved_order = Case(
                    *[When(pk=pk, then=pos) for pos, pk in enumerate(hit_ids)], 
                    output_field=IntegerField()
                )
                queryset = queryset.filter(id__in=hit_ids).order_by(preserved_order)
            else:
                queryset = queryset.none()
                
        except Exception as e:
            print(f"⚠️ Meilisearch 搜索不可用，降级为原生数据库查询: {e}")
            queryset = queryset.filter(
                Q(title__icontains=query) |
                Q(searchable_prompts__icontains=query) |
                Q(model_info__icontains=query) |       
                Q(characters__name__icontains=query) | 
                Q(tags__name__icontains=query)
            ).distinct()
    
    # 基础状态筛选
    if f_liked == '1' or filter_type == 'liked':
        queryset = queryset.filter(is_liked=True)
    if f_video == '1':
        queryset = queryset.filter(
            # 1. 检查多图列表里是否包含视频
            Q(images__image__icontains='.mp4') |
            Q(images__image__icontains='.mov') |
            Q(images__image__icontains='.avi') |
            Q(images__image__icontains='.webm') |
            Q(images__image__icontains='.mkv') |
            # 2. 修复：跨表检查 cover_image 外键里的 image 字段
            Q(cover_image__image__icontains='.mp4') |
            Q(cover_image__image__icontains='.mov') |
            Q(cover_image__image__icontains='.webm')
        ).distinct()
    if f_multi == '1':
        queryset = queryset.annotate(img_count=Count('images')).filter(img_count__gt=1)
        
    # 模型筛选 (OR 逻辑：选了A或B都展示)
    if f_models:
        queryset = queryset.filter(model_info__in=f_models)
        
    # 人物筛选 (OR 逻辑)
    if f_chars:
        queryset = queryset.filter(characters__name__in=f_chars).distinct()
        
    # 标签筛选 (AND 逻辑：必须同时包含选中的多个标签，用于精准定位)
    if f_tags:
        for t in f_tags:
            queryset = queryset.filter(tags__name=t)

    # === 版本去重与计数逻辑 ===
    version_counts = {}
    
    # 判断当前是否处于“高级筛选”状态
    is_filtering = any([f_liked, filter_type == 'liked', f_video, f_multi, f_models, f_chars, f_tags])    
    # 只有在：没搜文字、没以图搜图、且【没有开启任何组合筛选】时，才折叠去重
    if not query and not search_id and not is_filtering:
        group_stats = PromptGroup.objects.values('group_id').annotate(
            main_id=Max(Case(When(is_main_variant=True, then='id'), output_field=IntegerField())),
            latest_id=Max('id'),
            count=Count('id')
        )
        final_ids = []
        for s in group_stats:
            target_id = s['main_id'] if s['main_id'] else s['latest_id']
            final_ids.append(target_id)
            version_counts[target_id] = s['count']
        
        queryset = queryset.filter(id__in=final_ids)

    if not query and not search_id:
        queryset = queryset.order_by('-created_at', '-id')

    # === 统一执行 N+1 预加载 ===
    # 无论上面走了哪个分支，最后统一下达预加载指令，将首页原本的 40+ 次查询压缩到 4 次
    queryset = queryset.select_related(
        'cover_image'
    ).prefetch_related(
        'images', 'tags', 'characters', 'references'
    )
    # === 收集提供给前端侧边栏的数据 ===
    tags_bar = get_tags_bar_data()

    # 获取所有的模型名称列表
    model_names_list = list(_get_visible_model_suggestion_queryset().values_list('name', flat=True))
    
    # 获取各维度筛选项并统计卡片数量 (过滤掉没有作品被关联的空标签/人物)
    filter_data = {
        'models': model_names_list,
        'chars': Character.objects.annotate(use_count=Count('promptgroup')).filter(use_count__gt=0).order_by('-use_count'),
        # 获取最常用的前 50 个普通标签（排除掉作为模型名的标签，防止和模型筛选重复）
        'tags': Tag.objects.exclude(name__in=model_names_list).annotate(use_count=Count('promptgroup')).filter(use_count__gt=0).order_by('-use_count')[:50]
    }

    # === 分页与数据组装 ===
    paginator = Paginator(queryset, 12)
    page_number = request.GET.get('page')
    page = paginator.get_page(page_number)
    page_obj = paginator.get_page(page_number)
    page_range = page.paginator.get_elided_page_range(page.number, on_each_side=5, on_ends=1)
    # 统计总卡片数量
    total_groups_count = PromptGroup.objects.values('group_id').distinct().count()
    # 将计算好的版本数量绑定到每个对象上供前端展示
    for group in page_obj:
        group.version_count = version_counts.get(group.id, 0)

    # 复制一份当前的 GET 请求参数，把 'page' 剔除掉，剩下的打包成 url 字符串
    query_dict = request.GET.copy()
    if 'page' in query_dict:
        del query_dict['page']
    url_params = query_dict.urlencode()

    return render(request, 'gallery/home.html', {
        'groups': page,
        'page_obj': page_obj,
        'page_range': page_range,
        'search_query': query,
        'current_filter': filter_type,
        'tags_bar': tags_bar,
        'total_groups_count': total_groups_count,
        'filter_data': filter_data,
        'f_liked': f_liked,
        'f_video': f_video,
        'f_multi': f_multi,
        'f_models': f_models,
        'f_chars': f_chars,
        'f_tags': f_tags,
        'url_params': url_params,
    })


def liked_images_gallery(request):
    queryset = ImageItem.objects.filter(is_liked=True).select_related('group').order_by('-id')
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
            Q(group__searchable_prompts__icontains=query_text) |
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
    ensure_ai_studio_model_labels_registered()
    sort_mode = _normalize_detail_sort_mode(request.GET.get('sort'))
    ratio_filter = _normalize_detail_ratio_filter(request.GET.get('ratio'))

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
            Q(searchable_prompts__icontains=query) |
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
    latest_images_list = [item for item in all_items if not item.is_video]
    similar_images_list = _order_images_by_similarity(latest_images_list)

    for index, item in enumerate(latest_images_list):
        item.detail_sort_latest_order = index

    for index, item in enumerate(similar_images_list):
        item.detail_sort_similar_order = index

    images_list = similar_images_list if sort_mode == 'similar' else latest_images_list
    videos_list = [item for item in all_items if item.is_video]

    gallery_media_json = json.dumps([
        {
            'url': item.image.url,
            'id': item.pk,
            'isLiked': item.is_liked,
            'isVideo': item.is_video,
        }
        for item in [*images_list, *videos_list]
        if item.image
    ], ensure_ascii=False)

    detail_config_json = json.dumps({
        'groupId': str(group.pk or ''),
        'rawPromptContent': group.prompt_text or group.title or '',
        'sortMode': sort_mode,
        'ratioFilter': ratio_filter,
        'ratioGroupsUrl': reverse('detail_ratio_groups', args=[group.pk]),
    }, ensure_ascii=False)
    
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
    current_prompt = group.searchable_prompts or group.prompt_text or ""
    
    for sib in siblings_qs:
        sib_prompt = sib.searchable_prompts or sib.prompt_text or ""
        sib.diff_html = generate_diff_html(current_prompt, sib_prompt)
        siblings.append(sib)

    # 1. 获取当前卡片的标签 ID 列表
    tag_ids = group.tags.values_list('id', flat=True)

    if not tag_ids:
        related_groups = []
    else:
        related_groups = PromptGroup.objects.filter(
            tags__id__in=tag_ids
        ).exclude(
            group_id=group.group_id
        ).annotate(
            same_tag_count=Count('tags')
        ).order_by(
            '-same_tag_count',
            '?'
        ).distinct().select_related('cover_image').prefetch_related('images')[:4]
    
    tags_bar = get_tags_bar_data()
    all_models_list = _get_visible_model_suggestion_queryset().values_list('name', flat=True).order_by('name')
    provider_choices = list(PROVIDER_CHOICES)

    # char_refs_data = []
    # all_chars_for_ref = Character.objects.all().order_by('-order', 'name')
    
    # for char in all_chars_for_ref:
    #     # 1. 查出带有该人物标签的所有参考图记录（按时间倒序，最新的在前）
    #     raw_refs = ReferenceItem.objects.filter(group__characters=char).order_by('-id')
        
    #     unique_refs = []
    #     seen_identifiers = set() # 用于记忆已经挑出来的图片指纹
        
    #     for ref in raw_refs:
    #         if not ref.image:
    #             continue
                
    #         # 2. 提取指纹：优先使用刚加上的 MD5 哈希，如果没有则使用文件路径
    #         fingerprint = ref.image_hash if ref.image_hash else ref.image.name
            
    #         # 3. 如果这个指纹还没见过，说明是“新面孔”，加入展示列表
    #         if fingerprint not in seen_identifiers:
    #             seen_identifiers.add(fingerprint)
    #             unique_refs.append(ref)
                
    #         # 4. 凑够 12 张【不重复】的独立图片就收手
    #         if len(unique_refs) >= 12:
    #             break
                
    #     if unique_refs:
    #         char_refs_data.append({
    #             'character': char,
    #             'refs': unique_refs
    #         })
    char_refs_data = get_cached_char_refs_data()
    
    return render(request, 'gallery/detail.html', {
        'all_models_list': all_models_list,        
        'group': group,
        'prompt_entries': group.get_prompt_items(),
        'prompt_entries_json': json.dumps(group.get_prompt_items(), ensure_ascii=False),
        'sorted_tags': tags_list,
        'chars_list': chars_list,
        'all_tags': all_tags,
        'siblings': siblings,
        'related_groups': related_groups,
        'tags_bar': tags_bar,
        'search_query': request.GET.get('q'),
        'images_list': images_list,
        'videos_list': videos_list,
        'sort_mode': sort_mode,
        'ratio_filter': ratio_filter,
        'gallery_media_json': gallery_media_json,
        'detail_config_json': detail_config_json,
        'prev_group': prev_group,
        'next_group': next_group,
        'char_refs_data': char_refs_data,
        'provider_choices': provider_choices,
    })


@require_GET
def detail_ratio_groups(request, pk):
    group = get_object_or_404(
        PromptGroup.objects.prefetch_related(
            Prefetch('images', queryset=ImageItem.objects.order_by('-id')),
        ),
        pk=pk,
    )

    ratio_groups = {}
    for item in group.images.all():
        if item.is_video:
            continue
        ratio_groups[str(item.pk)] = _get_detail_ratio_group(item)

    return JsonResponse({'status': 'success', 'ratio_groups': ratio_groups})


def upload(request):
    ensure_ai_studio_model_labels_registered()
    if request.method == 'POST':
        prompt_items = extract_prompt_items_from_mapping(request.POST)
        prompt_text = get_primary_prompt_text(prompt_items)
        title = request.POST.get('title', '') or '未命名组'
        model_id = request.POST.get('model_info')
        provider = request.POST.get('provider', 'other')

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
            prompts=prompt_items,
            model_info=model_name_str,
            provider=provider,
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
        selected_chars = request.POST.getlist('characters')
        for char_id in selected_chars:
            if char_id.isdigit():
                try:
                    group.characters.add(char_id)
                except Exception as e:
                    print(f"添加人物标签失败: {e}")
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
                        
                        try:
                            if not ref.image.storage.exists(ref.image.name):
                                print(f"DEBUG: 原文件不存在于磁盘: {ref.image.name}")
                                continue

                            # 补全旧图的哈希（如果老图没有哈希）
                            if not ref.image_hash:
                                ref.calculate_hash()
                                ref.save(update_fields=['image_hash'])

                            # 直接复用哈希和路径，不再 read() 和 save() 文件内容
                            new_ref.image_hash = ref.image_hash
                            new_ref.image.name = ref.image.name
                            new_ref.save()
                            print("DEBUG: 参考图软引用复用成功")
                                
                        except Exception as inner_e:
                            print(f"DEBUG: 复用单个文件失败: {inner_e}")

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
            file_hash = calculate_file_hash(rf)
            existing_ref = ReferenceItem.objects.filter(image_hash=file_hash).first()
            
            # 如果这图库里已经有了，就软引用；如果没有，就正常创建
            if existing_ref and existing_ref.image and existing_ref.image.storage.exists(existing_ref.image.name):
                ref = ReferenceItem(group=group, image_hash=file_hash)
                ref.image.name = existing_ref.image.name
                ref.save()
            else:
                ReferenceItem.objects.create(group=group, image=rf, image_hash=file_hash)

        existing_ref_ids = request.POST.getlist('existing_ref_ids')
        if existing_ref_ids:
            for ref_id in existing_ref_ids:
                try:
                    old_ref = ReferenceItem.objects.get(id=ref_id)
                    if old_ref.image and old_ref.image.storage.exists(old_ref.image.name):
                        if not old_ref.image_hash:
                            old_ref.calculate_hash()
                            old_ref.save(update_fields=['image_hash'])
                            
                        # 完全软引用
                        new_ref = ReferenceItem(group=group, image_hash=old_ref.image_hash)
                        new_ref.image.name = old_ref.image.name 
                        new_ref.save()
                except Exception as e:
                    print(f"复用参考图失败 ID {ref_id}: {e}")

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
        initial_prompt_entries = PromptGroup.build_prompts_from_legacy_fields('', '', '')
        
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
                source_prompt_items = source_group.get_prompt_items()
                initial_prompt_entries = source_prompt_items
                initial_data = {
                    'title': source_group.title, # 可以选择加上 ' (新模型)' 后缀
                    'prompt_text': source_prompt_items[0]['text'] if len(source_prompt_items) >= 1 else '',
                    'prompt_text_zh': source_prompt_items[1]['text'] if len(source_prompt_items) >= 2 else '',
                    'negative_prompt': source_prompt_items[2]['text'] if len(source_prompt_items) >= 3 else '',
                    'prompts_json': json.dumps(source_prompt_items, ensure_ascii=False),
                    'tags': source_group.tags.all(),
                    # 注意：不预填充 model_info，强制用户选择新模型
                }
            except PromptGroup.DoesNotExist:
                pass
        else:
            initial_prompt_entries = PromptGroup.build_prompts_from_legacy_fields(
                initial_data.get('prompt_text', ''),
                initial_data.get('prompt_text_zh', ''),
                initial_data.get('negative_prompt', ''),
            )
        
        # char_refs_data = []
        # all_chars_for_ref = Character.objects.all().order_by('-order', 'name')
        
        # for char in all_chars_for_ref:
        #     raw_refs = ReferenceItem.objects.filter(group__characters=char).order_by('-id')
        #     unique_refs = []
        #     seen_identifiers = set() 
            
        #     for ref in raw_refs:
        #         if not ref.image: continue
        #         fingerprint = ref.image_hash if ref.image_hash else ref.image.name
        #         if fingerprint not in seen_identifiers:
        #             seen_identifiers.add(fingerprint)
        #             unique_refs.append(ref)
        #         if len(unique_refs) >= 12: break
                    
        #     if unique_refs:
        #         char_refs_data.append({'character': char, 'refs': unique_refs}) 

        char_refs_data = get_cached_char_refs_data()

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
            'char_refs_data': char_refs_data,
            'initial_prompt_entries_json': json.dumps(initial_prompt_entries, ensure_ascii=False),
        })


@csrf_exempt
def check_duplicates(request):
    """全库查重接口 (极致性能优化版：流式哈希 + 批量查询 + 解决 N+1)"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': '仅支持 POST 请求'})

    files = request.FILES.getlist('images')
    if not files:
        return JsonResponse({'status': 'error', 'message': '未检测到上传文件'})

    batch_id = uuid.uuid4().hex
    temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_uploads', batch_id)
    os.makedirs(temp_dir, exist_ok=True)

    file_data_list = []
    hash_list = []

    try:
        # ==========================================
        # 优化 1：边写入边计算 Hash，彻底消灭二次磁盘读取
        # ==========================================
        for file in files:
            file_path = os.path.join(temp_dir, file.name)
            md5_hash = hashlib.md5()
            
            with open(file_path, 'wb+') as destination:
                for chunk in file.chunks():
                    destination.write(chunk)
                    md5_hash.update(chunk)  # 边写硬盘边算哈希，榨干 IO 性能
            
            file_hash = md5_hash.hexdigest()
            hash_list.append(file_hash)
            
            relative_path = f"temp_uploads/{batch_id}/{file.name}"
            file_data_list.append({
                'filename': file.name,
                'hash': file_hash,
                'url': f"{settings.MEDIA_URL}{relative_path}"
            })

        # ==========================================
        # 优化 2 & 3：使用 __in 批量查询，并用 select_related 解决 N+1
        # ==========================================
        # 将几十上百次 SQL 查询合并为 1 次，并提前连表拿出 Group 的标题
        duplicates_qs = ImageItem.objects.select_related('group').filter(image_hash__in=hash_list)
        
        # 将查出来的重复项按照 hash 分组映射到内存字典中，查询时间复杂度降为 O(1)
        dup_map = defaultdict(list)
        for dup in duplicates_qs:
            dup_map[dup.image_hash].append(dup)

        # ==========================================
        # 4. 极速组装返回结果
        # ==========================================
        results = []
        for item in file_data_list:
            f_hash = item['hash']
            dups = dup_map.get(f_hash, [])
            is_duplicate = len(dups) > 0
            
            dup_info = []
            for dup in dups:
                dup_info.append({
                    'id': dup.id,
                    'group_id': dup.group.id,
                    'group_title': dup.group.title, # 因为有 select_related，这里不再触发查询
                    'is_video': dup.is_video,
                    'url': dup.thumbnail.url if dup.thumbnail else dup.image.url
                })

            results.append({
                'filename': item['filename'],
                'status': 'duplicate' if is_duplicate else 'pass',
                'url': item['url'],
                'thumbnail_url': item['url'],
                'duplicates': dup_info
            })
            
    except Exception as e:
        import traceback
        traceback.print_exc()
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
                html_list, new_images_data = _build_detail_new_images_payload(request, new_images)

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
            existing_ref_ids = request.POST.getlist('existing_ref_ids')
            new_refs = []
            # 处理本地新上传的图
            if files:
                for f in files:
                    file_hash = calculate_file_hash(f)
                    existing_ref = ReferenceItem.objects.filter(image_hash=file_hash).first()
                    
                    if existing_ref and existing_ref.image and existing_ref.image.storage.exists(existing_ref.image.name):
                        # 【去重】：不保存新文件，直接复用老文件的路径
                        ref = ReferenceItem(group=group, image_hash=file_hash)
                        ref.image.name = existing_ref.image.name
                        ref.save()
                    else:
                        ref = ReferenceItem.objects.create(group=group, image=f, image_hash=file_hash)
                    new_refs.append(ref)
            # 【新增】处理从图库中快捷选择的老图 (物理复制一份文件防互相影响)
            if existing_ref_ids:
                for ref_id in existing_ref_ids:
                    try:
                        old_ref = ReferenceItem.objects.get(id=ref_id)
                        if old_ref.image and old_ref.image.storage.exists(old_ref.image.name):
                            # 补全旧图的哈希
                            if not old_ref.image_hash:
                                old_ref.calculate_hash()
                                old_ref.save(update_fields=['image_hash'])
                                
                            # 【去重】：完全不再物理复制，直接软引用复用路径！
                            new_ref = ReferenceItem(group=group, image_hash=old_ref.image_hash)
                            new_ref.image.name = old_ref.image.name 
                            new_ref.save()
                            new_refs.append(new_ref)
                    except Exception as e:
                        print(f"复用参考图失败 ID {ref_id}: {e}")
            
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
                # 【新增】删除整组时也要排查参考图是否被借用
                is_shared = False
                if ref.image_hash:
                    is_shared = ReferenceItem.objects.filter(image_hash=ref.image_hash).exclude(group=group).exists()
                if not is_shared:
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
            if item.image:
                # 【新增】检查是否还有其他卡片在复用这个物理文件
                is_shared = False
                if item.image_hash:
                    is_shared = ReferenceItem.objects.filter(image_hash=item.image_hash).exclude(pk=item.pk).exists()
                
                # 只有在这张图完全没有被其他人引用的情况下，才从硬盘物理删除
                if not is_shared:
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
        if 'prompts' in data:
            group.prompts = normalize_prompt_items(data.get('prompts'))
        elif any(key in data for key in ['prompt_text', 'prompt_text_zh', 'negative_prompt']):
            legacy_prompt_items = PromptGroup.build_prompts_from_legacy_fields(
                data['prompt_text'] if 'prompt_text' in data else group.prompt_text,
                data['prompt_text_zh'] if 'prompt_text_zh' in data else group.prompt_text_zh,
                data['negative_prompt'] if 'negative_prompt' in data else group.negative_prompt,
            )
            group.prompts = legacy_prompt_items

        duplicate_prompts = find_duplicate_prompt_texts(group.prompts)
        if duplicate_prompts:
            duplicate_preview = '；'.join(duplicate_prompts[:3])
            if len(duplicate_prompts) > 3:
                duplicate_preview += '；...'
            return JsonResponse({
                'status': 'error',
                'message': f'提示词组中存在重复内容，请删除重复项后再保存：{duplicate_preview}'
            }, status=400)

        if 'model_info' in data:
            group.model_info = data['model_info']
        if 'provider' in data:                    
            group.provider = data['provider']
            
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
    query = request.GET.get('q', '').strip()
    page_num = request.GET.get('page', 1)
    include_variants = request.GET.get('include_variants') == '1'
    
    qs = PromptGroup.objects.all()
    count_map = {}
    
    if query:
        search_filter = (
            Q(title__icontains=query) |
            Q(searchable_prompts__icontains=query) |
            Q(model_info__icontains=query) |       # 加上模型搜索
            Q(characters__name__icontains=query) | # 加上人物搜索
            Q(tags__name__icontains=query)
        )
        matching_group_ids = list(
            qs.filter(search_filter).values_list('group_id', flat=True).distinct()
        )

        if include_variants:
            final_qs = PromptGroup.objects.filter(group_id__in=matching_group_ids).order_by('-id')
            count_map = {
                item['group_id']: item['count']
                for item in PromptGroup.objects.filter(group_id__in=matching_group_ids)
                .values('group_id')
                .annotate(count=Count('id'))
            }
        else:
            qs = qs.filter(group_id__in=matching_group_ids)
            group_stats = qs.values('group_id').annotate(
                main_id=Max(Case(When(is_main_variant=True, then='id'), output_field=IntegerField())),
                max_id=Max('id'),
                count=Count('id')
            )

            target_ids = [(item['main_id'] or item['max_id']) for item in group_stats]
            count_map = {(item['main_id'] or item['max_id']): item['count'] for item in group_stats}
            final_qs = PromptGroup.objects.filter(id__in=target_ids).order_by('-id')
    else:
        group_stats = qs.values('group_id').annotate(
            main_id=Max(Case(When(is_main_variant=True, then='id'), output_field=IntegerField())),
            max_id=Max('id'),
            count=Count('id')
        )

        target_ids = [(item['main_id'] or item['max_id']) for item in group_stats]
        count_map = {(item['main_id'] or item['max_id']): item['count'] for item in group_stats}
        final_qs = PromptGroup.objects.filter(id__in=target_ids).order_by('-id')

    final_qs = final_qs.select_related('cover_image').prefetch_related('images', 'characters')
    
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
            'prompt_text': get_prompt_summary_text(group),
            'created_at': group.created_at.strftime('%Y-%m-%d'),
            'cover_url': cover_url,
            'model_info': group.model_info or '',
            'characters': [char.name for char in group.characters.all()],
            'group_id': str(group.group_id),
            'count': count_map.get(group.group_id, count_map.get(group.id, 1))
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
    """获取相似提示词的推荐候选 (用于关联版本) - ORM 极限优化版"""
    try:
        current_group = PromptGroup.objects.get(pk=pk)
    except PromptGroup.DoesNotExist:
        return JsonResponse({'status': 'error', 'message': 'Group not found'})

    my_content = (current_group.searchable_prompts or current_group.prompt_text or "").strip().lower()
    if len(my_content) < 5:
         return JsonResponse({'status': 'success', 'results': []})

    my_words = set(w for w in re.split(r'[\s,，.。;；|()（）]+', my_content) if len(w) > 2)

    group_stats = PromptGroup.objects.values('group_id').annotate(max_id=Max('id'))
    latest_ids = [item['max_id'] for item in group_stats]
    
    # 【核心优化1】：用 values_list 只取 id 和 文本，不取完整对象
    candidates_data = PromptGroup.objects.filter(id__in=latest_ids).exclude(
        group_id=current_group.group_id
    ).values_list('id', 'searchable_prompts').order_by('-id')[:1000]
    
    recommendations = []
    
    for other_id, other_content in candidates_data:
        other_content = (other_content or "").strip().lower()
        if not other_content: continue
        
        max_len = max(len(my_content), len(other_content))
        if max_len == 0: continue
        if abs(len(my_content) - len(other_content)) > max_len * 0.7: 
            continue

        other_words = set(w for w in re.split(r'[\s,，.。;；|()（）]+', other_content) if len(w) > 2)
        if my_words and other_words:
            overlap = len(my_words.intersection(other_words))
            max_possible = min(len(my_words), len(other_words))
            if max_possible > 0 and (overlap / max_possible) < 0.15:
                continue

        ratio = fuzz.ratio(my_content, other_content) / 100.0
        
        if ratio > 0.3: 
            recommendations.append((ratio, other_id))
            
    recommendations.sort(key=lambda x: x[0], reverse=True)
    top_recs = recommendations[:20]
    
    top_ids = [item[1] for item in top_recs]
    
    # 【核心优化2】：一次性提取前 20 的完整对象并预加载图片
    groups_dict = PromptGroup.objects.prefetch_related('images').in_bulk(top_ids)
    
    results = []
    for ratio, group_id in top_recs:
        if group_id not in groups_dict:
            continue
            
        group = groups_dict[group_id]
        cover_url = ""
        cover_img = group.cover_image 
        
        if not cover_img:
            images = group.images.all()
            for img in images:
                if not img.is_video:
                    cover_img = img
                    break
            if not cover_img and images:
                cover_img = images[0]
        
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
            'prompt_text': get_prompt_summary_text(group, max_length=200),
            'cover_url': cover_url,
            'similarity': f"{int(ratio*100)}%" 
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
    ensure_ai_studio_model_labels_registered()
    template_id = request.GET.get('template_id')
    prompt_type = request.GET.get('prompt_type', 'positive')
    model_names = set(AIModel.objects.values_list('name', flat=True))
    
    initial_data = {'prompt': '', 'tags': [], 'characters': [], 'reference_urls': []}
    
    if template_id:
        try:
            source_group = PromptGroup.objects.get(pk=template_id)
            source_prompt_items = source_group.get_prompt_items()
            
            selected_prompt = ""
            legacy_type_to_index = {'positive': 0, 'positive_zh': 1, 'negative': 2}
            if prompt_type.isdigit():
                prompt_index = max(int(prompt_type) - 1, 0)
            else:
                prompt_index = legacy_type_to_index.get(prompt_type, 0)

            if 0 <= prompt_index < len(source_prompt_items):
                selected_prompt = source_prompt_items[prompt_index]['text']
            else:
                selected_prompt = source_group.get_primary_prompt_text()
                
            tags = [tag.name for tag in source_group.tags.all() if tag.name not in model_names]

            chars = []
            if hasattr(source_group, 'characters'):
                chars = [char.name for char in source_group.characters.all()]
            
            ref_urls = [ref.image.url for ref in source_group.references.all() if ref.image]
            if not ref_urls:
                first_img = source_group.images.first()
                if first_img and first_img.image:
                    ref_urls.append(first_img.image.url)
            source_model_info = source_group.model_info or ""
            matched_full_title = source_model_info
                
            import re
            candidates = []
            for m_key, m_cfg in AI_STUDIO_CONFIG['models'].items():
                cfg_title = m_cfg.get('title', '')
                # 将配置表里的带括号名字洗净
                clean_cfg_title = re.sub(r'\s*[\(（].*?[\)）]$', '', cfg_title).strip()
                if clean_cfg_title.lower() == source_model_info.lower():
                    candidates.append(m_cfg)
                
            if candidates:
                # 尝试精确匹配 provider (区分同一个模型的 Fal 版和官方版)
                group_provider = getattr(source_group, 'provider', 'other')
                exact_match = next((cfg for cfg in candidates if cfg.get('provider') == group_provider), None)
                if exact_match:
                    matched_full_title = exact_match['title']
                else:
                    # 兜底：如果没精准匹配上，给列表里的第一个同名模型保证前端不报错
                    matched_full_title = candidates[0]['title']
                    
            initial_data = {
                'prompt': selected_prompt, 
                'prompts': source_prompt_items,
                'tags': tags, 
                'characters': chars,
                'reference_urls': ref_urls,
                'model_info': matched_full_title 
            }
        except PromptGroup.DoesNotExist:
            pass

    # 【新增】获取全库所有已有的标签名称列表
    all_tags = list(
        Tag.objects.exclude(name__in=model_names)
        .values_list('name', flat=True)
        .distinct()
    )
    all_chars = []
    try:
        from .models import Character
        all_chars = list(Character.objects.values_list('name', flat=True).distinct())
    except Exception:
        pass

    # char_refs_data = []
    # all_chars_for_ref = Character.objects.all().order_by('-order', 'name')
    # for char in all_chars_for_ref:
    #     raw_refs = ReferenceItem.objects.filter(group__characters=char).order_by('-id')
    #     unique_refs = []
    #     seen_identifiers = set() 
    #     for ref in raw_refs:
    #         if not ref.image: continue
    #         fingerprint = ref.image_hash if ref.image_hash else ref.image.name
    #         if fingerprint not in seen_identifiers:
    #             seen_identifiers.add(fingerprint)
    #             unique_refs.append(ref)
    #         if len(unique_refs) >= 12: break
    #     if unique_refs:
    #         char_refs_data.append({'character': char, 'refs': unique_refs})

    char_refs_data = get_cached_char_refs_data()

    return render(request, 'gallery/create.html', {
        'ai_config_json': json.dumps(AI_STUDIO_CONFIG),
        'initial_data_json': json.dumps(initial_data),
        'all_tags_json': json.dumps(all_tags),
        'all_chars_json': json.dumps(all_chars),
        'char_refs_data': char_refs_data,
    })

@csrf_exempt
@require_POST
def api_generate_and_download(request):
    try:
        prompt = request.POST.get('prompt', '').strip()
        model_choice = request.POST.get('model_choice')
        base_image_files = request.FILES.getlist('base_images') 
        extra_files = {}
        model_config = _get_ai_studio_model_config(model_choice)
        for file_param in model_config.get('file_params', []):
            file_obj = request.FILES.get(file_param['id'])
            if file_obj:
                extra_files[file_param['id']] = file_obj

        try:
            generation_result = _run_ai_studio_generation(
                model_choice,
                prompt,
                request.POST,
                base_image_files=base_image_files,
                extra_files=extra_files,
            )
        except (ValueError, RuntimeError) as exc:
            return JsonResponse({'status': 'error', 'message': str(exc)})

        if generation_result.get('failed'):
            return JsonResponse({
                'status': 'moderation_failed',
                'message': generation_result['message'],
                'error_code': generation_result.get('error_code', ''),
                'optimized_prompt': generation_result['optimized_prompt'],
                'prompt_mediation': generation_result['prompt_mediation'],
                'attempted_optimization_level': generation_result.get('attempted_optimization_level', ''),
                'can_retry_higher': generation_result.get('can_retry_higher', False),
                'next_optimization_level': generation_result.get('next_optimization_level', ''),
            })

        return JsonResponse({
            'status': 'success',
            'message': f"成功生成并下载了 {len(generation_result['saved_paths'])} 张图片！",
            'image_urls': generation_result['image_urls'],
            'saved_paths': generation_result['saved_paths'],
            'optimized_prompt': generation_result['optimized_prompt'],
            'prompt_mediation': generation_result['prompt_mediation'],
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)}, status=500)


@csrf_exempt
@require_POST
def api_create_gpt_image_conversation(request):
    try:
        source_page = request.POST.get('source_page', 'create').strip() or 'create'
        valid_source_pages = {choice[0] for choice in GPT_IMAGE_CONVERSATION_SOURCE_CHOICES}
        if source_page not in valid_source_pages:
            return JsonResponse({'status': 'error', 'message': '无效的来源页面'}, status=400)

        model_choice = request.POST.get('model_choice', '').strip()
        try:
            model_config = _get_ai_studio_model_config(model_choice)
        except ValueError as exc:
            return JsonResponse({'status': 'error', 'message': str(exc)}, status=400)

        if not _is_gpt_image_2_model(model_config):
            return JsonResponse({'status': 'error', 'message': '当前仅支持 GPT Image 2 创建对话调图会话'}, status=400)

        source_prompt_group = None
        source_prompt_group_id = request.POST.get('source_prompt_group_id')
        if source_prompt_group_id:
            source_prompt_group = PromptGroup.objects.filter(pk=source_prompt_group_id).first()
            if not source_prompt_group:
                return JsonResponse({'status': 'error', 'message': '来源作品组不存在'}, status=404)

        source_image = None
        source_image_id = request.POST.get('source_image_id')
        if source_image_id:
            source_image = ImageItem.objects.filter(pk=source_image_id).select_related('group').first()
            if not source_image:
                return JsonResponse({'status': 'error', 'message': '来源图片不存在'}, status=404)

        active_image = None
        active_image_id = request.POST.get('active_image_id')
        if active_image_id:
            active_image = ImageItem.objects.filter(pk=active_image_id).first()
            if not active_image:
                return JsonResponse({'status': 'error', 'message': '当前激活图片不存在'}, status=404)

        active_image_path = request.POST.get('active_image_path', '').strip()
        conversation = GPTImageConversation(
            source_page=source_page,
            source_prompt_group=source_prompt_group,
            source_image=source_image,
            model_key=model_choice,
            model_label=_get_ai_studio_registry_name(model_config),
            provider=model_config.get('provider', 'other'),
            initial_prompt=request.POST.get('prompt', '').strip(),
            latest_params=_parse_json_object(request.POST.get('latest_params')),
        )
        conversation.set_active_image_state(active_image or source_image, active_image_path)
        conversation.save()

        conversation = GPTImageConversation.objects.prefetch_related('turns').get(pk=conversation.pk)
        return JsonResponse({'status': 'success', 'conversation': _serialize_gpt_image_conversation(conversation, include_turns=True)})
    except Exception as exc:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(exc)}, status=500)


@require_GET
def api_list_gpt_image_conversations(request):
    source_page = request.GET.get('source_page', '').strip()
    source_prompt_group_id = request.GET.get('source_prompt_group_id', '').strip()
    limit_raw = request.GET.get('limit', '8').strip()

    queryset = GPTImageConversation.objects.select_related('source_prompt_group', 'source_image', 'active_image').prefetch_related('turns').order_by('-updated_at', '-id')

    if source_page:
        queryset = queryset.filter(source_page=source_page)

    if source_prompt_group_id:
        queryset = queryset.filter(source_prompt_group_id=source_prompt_group_id)

    try:
        limit = max(1, min(int(limit_raw), 20))
    except ValueError:
        limit = 8

    conversations = [_serialize_gpt_image_conversation_summary(conversation) for conversation in queryset[:limit]]
    return JsonResponse({'status': 'success', 'conversations': conversations})


@require_GET
def api_get_gpt_image_conversation(request, conversation_id):
    conversation = get_object_or_404(
        GPTImageConversation.objects.select_related('source_prompt_group', 'source_image', 'active_image').prefetch_related('turns'),
        conversation_id=conversation_id,
    )
    return JsonResponse({'status': 'success', 'conversation': _serialize_gpt_image_conversation(conversation, include_turns=True)})


@csrf_exempt
@require_POST
def api_append_gpt_image_conversation_turn(request, conversation_id):
    conversation = get_object_or_404(
        GPTImageConversation.objects.select_related('active_image', 'source_image').prefetch_related('turns'),
        conversation_id=conversation_id,
    )

    instruction = request.POST.get('instruction', '').strip() or request.POST.get('prompt', '').strip()
    if not instruction:
        return JsonResponse({'status': 'error', 'message': '调整指令不能为空'}, status=400)

    try:
        base_image_files = _build_conversation_base_images(conversation)
    except FileNotFoundError as exc:
        return JsonResponse({'status': 'error', 'message': str(exc)}, status=400)

    if not base_image_files:
        return JsonResponse({'status': 'error', 'message': '当前会话还没有可继续调整的基底图'}, status=400)

    extra_files = {}
    mask_file = request.FILES.get('mask_url')
    if mask_file:
        extra_files['mask_url'] = mask_file

    try:
        generation_result = _run_ai_studio_generation(
            conversation.model_key,
            instruction,
            request.POST,
            base_image_files=base_image_files,
            extra_files=extra_files,
        )
    except (ValueError, RuntimeError) as exc:
        return JsonResponse({'status': 'error', 'message': str(exc)}, status=400)

    if generation_result.get('failed'):
        return JsonResponse({
            'status': 'moderation_failed',
            'message': generation_result['message'],
            'error_code': generation_result.get('error_code', ''),
            'conversation': _serialize_gpt_image_conversation(conversation, include_turns=True),
            'optimized_prompt': generation_result['optimized_prompt'],
            'prompt_mediation': generation_result['prompt_mediation'],
            'attempted_optimization_level': generation_result.get('attempted_optimization_level', ''),
            'can_retry_higher': generation_result.get('can_retry_higher', False),
            'next_optimization_level': generation_result.get('next_optimization_level', ''),
        })

    selected_output_index_raw = request.POST.get('selected_output_index', '0')
    try:
        selected_output_index = int(selected_output_index_raw)
    except (TypeError, ValueError):
        selected_output_index = 0

    saved_paths = generation_result['saved_paths']
    if not saved_paths:
        return JsonResponse({'status': 'error', 'message': '本地未保存任何生成结果'}, status=500)

    selected_output_index = max(0, min(selected_output_index, len(saved_paths) - 1))
    active_output_path = saved_paths[selected_output_index]

    with transaction.atomic():
        next_turn_index = (conversation.turns.aggregate(max_turn=Max('turn_index')).get('max_turn') or 0) + 1
        turn = GPTImageConversationTurn.objects.create(
            conversation=conversation,
            turn_index=next_turn_index,
            instruction=instruction,
            input_image=conversation.active_image,
            input_image_path=conversation.active_image_path or getattr(getattr(conversation.active_image, 'image', None), 'name', '') or '',
            mask_image_path=getattr(mask_file, 'name', '') if mask_file else '',
            output_image_path=active_output_path,
            request_payload=generation_result['api_args'],
            response_payload={
                'image_urls': generation_result['image_urls'],
                'saved_paths': saved_paths,
                'selected_output_index': selected_output_index,
                'prompt_mediation': generation_result['prompt_mediation'],
            },
        )

        conversation.last_instruction = instruction
        conversation.latest_params = generation_result['api_args']
        conversation.set_active_image_state(image_path=active_output_path)
        conversation.save(update_fields=['active_image', 'active_image_path', 'last_instruction', 'latest_params', 'updated_at'])

    refreshed_conversation = GPTImageConversation.objects.prefetch_related('turns').get(pk=conversation.pk)
    return JsonResponse({
        'status': 'success',
        'conversation': _serialize_gpt_image_conversation(refreshed_conversation, include_turns=True),
        'turn': _serialize_gpt_image_conversation_turn(turn),
        'image_urls': generation_result['image_urls'],
        'saved_paths': saved_paths,
        'optimized_prompt': generation_result['optimized_prompt'],
        'prompt_mediation': generation_result['prompt_mediation'],
    })


@csrf_exempt
@require_POST
def api_set_gpt_image_conversation_active_result(request, conversation_id):
    conversation = get_object_or_404(GPTImageConversation, conversation_id=conversation_id)

    image_item = None
    image_id = request.POST.get('image_id')
    image_path = request.POST.get('image_path', '').strip()
    turn_id = request.POST.get('turn_id')

    if turn_id:
        turn = GPTImageConversationTurn.objects.filter(conversation=conversation, pk=turn_id).first()
        if not turn:
            return JsonResponse({'status': 'error', 'message': '指定轮次不存在'}, status=404)
        image_item = turn.output_image
        image_path = image_path or turn.output_image_path

    if image_id:
        image_item = ImageItem.objects.filter(pk=image_id).first()
        if not image_item:
            return JsonResponse({'status': 'error', 'message': '指定图片不存在'}, status=404)

    if not image_item and not image_path:
        return JsonResponse({'status': 'error', 'message': '请先指定要切换的结果图'}, status=400)

    conversation.set_active_image_state(image_item=image_item, image_path=image_path)
    conversation.save(update_fields=['active_image', 'active_image_path', 'updated_at'])
    return JsonResponse({'status': 'success', 'conversation': _serialize_gpt_image_conversation(conversation)})
    
@csrf_exempt
@require_POST
def api_publish_studio_creation(request):
    """处理从 AI 创作室一键发布作品卡片的请求"""
    try:
        prompt_items = extract_prompt_items_from_mapping(request.POST)
        prompt = get_primary_prompt_text(prompt_items)
        model_info = request.POST.get('model_info', '').strip()
        title = request.POST.get('title', '').strip()
        provider = request.POST.get('provider', 'other').strip()
        import re
        clean_model_info = re.sub(r'\s*[\(（].*?[\)）]$', '', model_info).strip()
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
            prompts=prompt_items,
            model_info=clean_model_info,
            provider=provider
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
    """根据前端传来的 Prompt 文本，计算全库相似度 (C++ 底层批处理极速版)"""
    try:
        data = json.loads(request.body)
        prompt_text = data.get('prompt', '').strip().lower()
        def build_prompt_meta(prompt_items):
            meta = []
            for index, item in enumerate(prompt_items, start=1):
                meta.append({
                    'field': item.get('id', f'prompt_{index}'),
                    'label': item.get('label', f'提示词{index}'),
                    'text': item.get('text', ''),
                })
            return meta
        
        candidate_groups = list(
            PromptGroup.objects.only('id', 'prompts', 'prompt_text', 'prompt_text_zh', 'negative_prompt')
            .order_by('-id')[:2000]
        )
        
        if not prompt_text:
            # 如果没传提示词，直接按最新时间返回兜底数据
            top_recs = []
            for group in candidate_groups[:15]:
                prompt_meta = build_prompt_meta(group.get_prompt_items())
                matched_meta = prompt_meta[0] if prompt_meta else {
                    'field': 'prompt_1',
                    'label': '提示词1',
                    'text': '',
                }
                top_recs.append({
                    'ratio': 0.0,
                    'group_id': group.id,
                    'matched_field': matched_meta['field'],
                    'matched_label': matched_meta['label'],
                    'matched_text': matched_meta['text'],
                })
        else:
            # 2. 将统一提示词列表里的每一项全部纳入匹配池
            valid_choices = {}
            choice_meta = {}
            for group in candidate_groups:
                for prompt_meta in build_prompt_meta(group.get_prompt_items()):
                    raw_text = prompt_meta['text']
                    normalized_text = raw_text.strip().lower()
                    if normalized_text:
                        choice_key = f'{group.id}:{prompt_meta["field"]}'
                        valid_choices[choice_key] = normalized_text
                        choice_meta[choice_key] = {
                            'group_id': group.id,
                            'field_name': prompt_meta['field'],
                            'field_label': prompt_meta['label'],
                            'raw_text': raw_text.strip(),
                        }
                    
            # 3. 批量计算多个字段的相似度，再按组聚合取最高分
            matches = process.extract(
                prompt_text,
                valid_choices,
                scorer=fuzz.ratio,
                limit=min(len(valid_choices), 120) if valid_choices else 0
            )
            
            best_scores = {}
            for _, score, choice_key in matches:
                meta = choice_meta[str(choice_key)]
                group_id = meta['group_id']
                old_score = best_scores.get(group_id)
                if old_score is None or score > old_score['score']:
                    best_scores[group_id] = {
                        'score': score,
                        'matched_field': meta['field_name'],
                        'matched_label': meta['field_label'],
                        'matched_text': meta['raw_text'],
                    }

            top_recs = [
                {
                    'ratio': match_info['score'] / 100.0,
                    'group_id': group_id,
                    'matched_field': match_info['matched_field'],
                    'matched_label': match_info['matched_label'],
                    'matched_text': match_info['matched_text'],
                }
                for group_id, match_info in sorted(
                    best_scores.items(),
                    key=lambda item: (-item[1]['score'], -item[0])
                )[:15]
            ]
            
            # 4. 如果匹配结果不足 15 个（比如全被短路过滤了），用最新的 ID 补齐兜底
            if len(top_recs) < 15:
                used_ids = {rec['group_id'] for rec in top_recs}
                for group in candidate_groups:
                    if group.id not in used_ids:
                        prompt_meta = build_prompt_meta(group.get_prompt_items())
                        matched_meta = prompt_meta[0] if prompt_meta else {
                            'field': 'prompt_1',
                            'label': '提示词1',
                            'text': '',
                        }
                        top_recs.append({
                            'ratio': 0.0,
                            'group_id': group.id,
                            'matched_field': matched_meta['field'],
                            'matched_label': matched_meta['label'],
                            'matched_text': matched_meta['text'],
                        })
                        if len(top_recs) >= 15:
                            break

        top_ids = [item['group_id'] for item in top_recs]
        
        groups_dict = PromptGroup.objects.select_related('cover_image').prefetch_related('images', 'characters').in_bulk(top_ids)
        
        results = []
        for rec in top_recs:
            ratio = rec['ratio']
            group_id = rec['group_id']
            if group_id not in groups_dict:
                continue
                
            group = groups_dict[group_id]
            cover_url = ""
            cover_img = group.cover_image
            
            if not cover_img:
                images = group.images.all() 
                for img in images:
                    if not img.is_video:
                        cover_img = img
                        break
                if not cover_img and images:
                    cover_img = images[0]
            
            if cover_img:
                 try:
                    if not cover_img.is_video and cover_img.thumbnail:
                        cover_url = cover_img.thumbnail.url
                    else:
                        cover_url = cover_img.image.url
                 except:
                     pass
            
            chars_list = []
            if hasattr(group, 'characters'):
                chars_list = [char.name for char in group.characters.all()]

            matched_prompt_text = rec['matched_text'] or group.prompt_text or group.prompt_text_zh or group.negative_prompt or '无提示词'
            if len(matched_prompt_text) > 100:
                matched_prompt_text = matched_prompt_text[:100] + '...'
                     
            results.append({
                'id': group.id,
                'title': group.title,
                'prompt_text': matched_prompt_text,
                'cover_url': cover_url,
                'similarity': f"{int(ratio*100)}%" if len(prompt_text) > 0 else "-",
                'model_info': group.model_info or "无模型",
                'characters': chars_list,
                'matched_prompt_field': rec['matched_field'],
                'matched_prompt_label': rec.get('matched_label', '提示词1')
            })
            
        return JsonResponse({'status': 'success', 'results': results})
    except Exception as e:
        import traceback
        traceback.print_exc()
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

        new_images = ImageItem.objects.filter(id__in=created_image_ids).order_by('id')
        html_list, new_images_data = _build_detail_new_images_payload(request, new_images)
            
        return JsonResponse({
            'status': 'success',
            'group_id': group.id,
            'message': '成功追加到该作品！',
            'new_images_html': html_list,
            'new_images_data': new_images_data,
            'type': 'gen',
        })
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

@require_POST
def merge_variants_api(request):
    """手动将选中的版本合并到当前提示词组 (批量性能优化版)"""
    try:
        data = json.loads(request.body)
        main_group_id = data.get('main_group_id')
        merge_ids = data.get('merge_ids', [])

        if not main_group_id or not merge_ids:
            return JsonResponse({'status': 'error', 'message': '参数不完整'})

        # 获取主卡片
        main_group = get_object_or_404(PromptGroup, id=main_group_id)
        
        # 获取需要被合并的卡片（排除自己，防止逻辑错误）
        groups_to_merge = PromptGroup.objects.filter(id__in=merge_ids).exclude(id=main_group_id)
        merged_count = groups_to_merge.count()

        if merged_count == 0:
            return JsonResponse({'status': 'success', 'message': '没有需要合并的版本。'})

        # 【核心优化】：开启事务，并在底层使用 SQL IN 进行批量操作
        with transaction.atomic():
            # 1. 批量转移生成图片和参考图 (几十条 SQL 压缩为 2 条)
            ImageItem.objects.filter(group__in=groups_to_merge).update(group=main_group)
            ReferenceItem.objects.filter(group__in=groups_to_merge).update(group=main_group)
            
            # 2. 如果主卡片没封面，从这些即将被销毁的组里随便借一个有封面的
            if not main_group.cover_image:
                # 找一个带有 cover_image 的被合并组
                first_valid_cover = groups_to_merge.exclude(cover_image__isnull=True).first()
                if first_valid_cover:
                    main_group.cover_image = first_valid_cover.cover_image
                    main_group.save(update_fields=['cover_image'])
                    
            # 3. 批量删除空壳组 (1 条 SQL 搞定全部删除)
            groups_to_merge.delete()

        return JsonResponse({
            'status': 'success', 
            'message': f'成功合并了 {merged_count} 个版本！'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': str(e)})
    
@csrf_exempt
def launch_comfyui(request):
    """一键启动本地 ComfyUI 服务"""
    if request.method == 'POST':
        try:
            if not os.path.exists(COMFYUI_BAT_PATH):
                return JsonResponse({'status': 'error', 'message': f'找不到启动脚本，请检查路径: {COMFYUI_BAT_PATH}'})

            # 获取 ComfyUI 所在的目录
            comfyui_dir = os.path.dirname(COMFYUI_BAT_PATH)
            
            # 【新增核心逻辑】：拷贝当前环境变量，并剔除 Django 虚拟环境的干扰
            clean_env = os.environ.copy()
            clean_env.pop('VIRTUAL_ENV', None)   # 剥离虚拟环境路径
            clean_env.pop('PYTHONPATH', None)    # 剥离 Python 搜索路径
            
            subprocess.Popen(
                ['cmd.exe', '/k', COMFYUI_BAT_PATH],
                cwd=comfyui_dir,
                env=clean_env,  # 【新增】：将干净的环境变量传给 ComfyUI
                creationflags=subprocess.CREATE_NEW_CONSOLE 
            )
            return JsonResponse({'status': 'success', 'message': '启动指令已发送'})
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': str(e)})
            
    return JsonResponse({'status': 'error', 'message': '仅支持 POST 请求'})


@csrf_exempt
@require_POST
def api_video_to_gif(request):
    try:
        # 1. 兼容性导入 MoviePy
        try:
            from moviepy import VideoFileClip
        except ImportError:
            from moviepy.editor import VideoFileClip

        video_file = request.FILES.get('video')
        start_time = float(request.POST.get('start_time', 0))
        end_time = float(request.POST.get('end_time', 5))
        
        # 【新增】：从前端获取目标帧率和宽度，并设置默认值
        target_fps = int(request.POST.get('fps', 12))
        target_width = int(request.POST.get('width', 480))
        
        # 限制最大帧率为 24，最大宽度为 720，防止恶意攻击搞挂服务器
        target_fps = min(target_fps, 60)
        target_width = min(target_width, 720)

        if not video_file:
            return JsonResponse({'status': 'error', 'message': '未检测到视频文件'})

        # 创建临时目录
        batch_id = str(uuid.uuid4())
        temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp_video_to_gif', batch_id)
        os.makedirs(temp_dir, exist_ok=True)

        in_path = os.path.join(temp_dir, video_file.name)
        with open(in_path, 'wb+') as f:
            for chunk in video_file.chunks():
                f.write(chunk)

        out_filename = f"GIF_{batch_id}.gif"
        out_dir = os.path.join(settings.MEDIA_ROOT, 'gifs')
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, out_filename)

        # 2. 核心处理：根据 MoviePy 版本自适应语法
        with VideoFileClip(in_path) as clip:
            
            # --- 兼容 subclipped (新) / subclip (旧) ---
            if hasattr(clip, 'subclipped'):
                subclip = clip.subclipped(start_time, end_time)  # MoviePy 2.x
            else:
                subclip = clip.subclip(start_time, end_time)     # MoviePy 1.x
            
            # --- 兼容 resized (新) / resize (旧) ---
            if hasattr(subclip, 'resized'):
                final_clip = subclip.resized(width=target_width)          # MoviePy 2.x
            else:
                final_clip = subclip.resize(width=target_width)           # MoviePy 1.x
            
            # 生成 GIF，使用前端传来的目标帧率
            final_clip.write_gif(out_path, fps=target_fps, logger=None)

        gif_url = f"{settings.MEDIA_URL}gifs/{out_filename}"
        
        # 清理临时视频
        if os.path.exists(in_path):
            os.remove(in_path)

        return JsonResponse({'status': 'success', 'gif_url': gif_url})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'status': 'error', 'message': f'转换失败: {str(e)}'}, status=500)