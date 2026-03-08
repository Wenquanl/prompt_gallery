import numpy as np
from PIL import Image
from sentence_transformers import SentenceTransformer
import torch
import os
import cv2  
import tempfile 
import faiss  # 【新增】FAISS 内存索引引擎
import requests # 【新增】用于请求本地 Ollama 服务
import json
import re

# ==========================================
# 全局变量 (仅保留 CLIP 模型和 FAISS 索引)
# ==========================================
_model = None
_faiss_index = None

# 【重要修改】已经删除了 _text_model 和 _text_tokenizer，不再占用显存

def load_model_on_startup():
    """
    系统启动时预加载图片向量模型，并构建 FAISS 索引
    """
    global _model
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    
    # 1. 加载 CLIP 模型 (用于以图搜图，必须保留)
    if _model is None:
        print(">>> [AI核心] 正在预加载 CLIP 模型...")
        try:
            _model = SentenceTransformer('clip-ViT-B-32', device=device)
            print(f">>> [AI核心] CLIP 模型加载完毕，运行设备: {device}")
        except Exception as e:
            print(f">>> [AI核心] ❌ 模型加载失败: {e}")
            
    # 2. 构建 FAISS 内存索引
    build_faiss_index()

# ==========================================
# 标题生成模块 (Ollama 异步 API 化)
# ==========================================
def generate_title_with_local_llm(prompt_text):
    """
    通过 HTTP 请求调用本地独立的 Ollama 服务进行标题概括，彻底解放 Django 进程
    """
    if not prompt_text:
        return None

    try:
        # 指向本地的 Ollama 服务接口
        ollama_url = "http://localhost:11434/api/generate"
        
        system_prompt = """你是一个专业的AI绘画策展人。请为下面的绘画提示词创作一个简短、有美感的中文作品标题。
要求：
1. 敏锐捕捉核心主体（如人物角色、核心场景）和环境意境。
2. 坚决忽略画质、镜头、光影和渲染参数（如masterpiece, 8k, unreal engine等）。
3. 必须是纯中文，高度凝练，严格控制在 7到 13 个字之间。
4. 直接输出最终标题，绝对不要带标点符号、引号或多余的解释。"""

        payload = {
            "model": "qwen2.5:1.5b",  # 确保你在终端跑过 ollama run qwen2.5:1.5b
            "prompt": f"提示词：{prompt_text}",
            "system": system_prompt,
            "stream": False,  
            "options": {
                "temperature": 0.1,
                "num_predict": 20 # 限制最大输出 token，防止生成废话
            }
        }

        # 设置 10 秒超时，防止 Ollama 卡死导致网页无响应
        response = requests.post(ollama_url, json=payload, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            title = result.get("response", "").strip()
            
            # 暴力清洗可能产生的意外标点符号
            title = re.sub(r'[^\u4e00-\u9fa5a-zA-Z0-9]', '', title)
            
            if title:
                print(f"✨ [Ollama] 成功生成标题: {title}")
                return title[:15]
                
        print(f"⚠️ [Ollama] 返回异常状态码: {response.status_code}")
        return None

    except requests.exceptions.Timeout:
        print("❌ [Ollama] 请求超时，请检查 Ollama 是否卡死，已降级处理")
        return None
    except requests.exceptions.ConnectionError:
        print("❌ [Ollama] 连接失败，请确保后台正在运行 Ollama")
        return None
    except Exception as e:
        print(f"❌ [Ollama] 调用发生未知错误: {e}")
        return None

# ==========================================
# 向量检索模块 (CLIP 编码)
# ==========================================
def get_model():
    global _model
    if _model is None:
        load_model_on_startup()
    return _model

def generate_image_embedding(image_path_or_file):
    """生成图片特征向量 (Bytes)"""
    model = get_model()
    if model is None:
        return None
        
    temp_video_path = None
    
    try:
        img = None
        is_video = False
        file_path = ""

        if isinstance(image_path_or_file, str):
            file_path = image_path_or_file
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']:
                is_video = True
        elif hasattr(image_path_or_file, 'name'):
            ext = os.path.splitext(image_path_or_file.name)[1].lower()
            if ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']:
                is_video = True
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    if hasattr(image_path_or_file, 'seek'): image_path_or_file.seek(0)
                    tmp.write(image_path_or_file.read())
                    temp_video_path = tmp.name
                    file_path = tmp.name

        if is_video:
            cap = cv2.VideoCapture(file_path)
            ret, frame = cap.read()
            cap.release()
            if ret:
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame)
        
        if img is None:
            img = Image.open(image_path_or_file)
        
        embedding = model.encode(img)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
            
        return embedding.astype(np.float32).tobytes()
        
    except Exception as e:
        print(f"生成特征向量失败: {e}")
        return None
    finally:
        if temp_video_path and os.path.exists(temp_video_path):
            try:
                os.remove(temp_video_path)
            except:
                pass

# ==========================================
# FAISS 高性能检索引擎模块
# ==========================================
def build_faiss_index():
    """初始化并构建 FAISS 全局倒排索引"""
    global _faiss_index
    from .models import ImageItem  # 局部引入，避免循环依赖
    
    print(">>> [FAISS] 正在构建全局向量索引...")
    dimension = 512
    base_index = faiss.IndexFlatIP(dimension)
    _faiss_index = faiss.IndexIDMap(base_index)
    
    # 分块读取数据库，防 OOM
    qs = ImageItem.objects.exclude(feature_vector__isnull=True).values_list('id', 'feature_vector')
    
    chunk_ids = []
    chunk_vectors = []
    
    for obj_id, vec_bytes in qs.iterator(chunk_size=5000):
        try:
            chunk_ids.append(obj_id)
            chunk_vectors.append(np.frombuffer(vec_bytes, dtype=np.float32))
        except Exception:
            continue
            
        if len(chunk_ids) >= 5000:
            _faiss_index.add_with_ids(
                np.array(chunk_vectors), 
                np.array(chunk_ids, dtype=np.int64)
            )
            chunk_ids.clear()
            chunk_vectors.clear()
            
    if chunk_ids:
        _faiss_index.add_with_ids(
            np.array(chunk_vectors), 
            np.array(chunk_ids, dtype=np.int64)
        )
        
    print(f">>> [FAISS] 向量索引构建完成！当前库中包含 {_faiss_index.ntotal} 张可检索图片。")

def add_to_faiss_index(db_id, vector_bytes):
    """动态追加单张新图片到 FAISS 索引，用于后台任务"""
    global _faiss_index
    if _faiss_index is None:
        return
    try:
        vec = np.frombuffer(vector_bytes, dtype=np.float32).reshape(1, -1)
        _faiss_index.add_with_ids(vec, np.array([db_id], dtype=np.int64))
    except Exception as e:
        print(f"动态追加 FAISS 索引失败: {e}")

def search_similar_images(query_image_file, queryset, top_k=50):
    """基于 FAISS 的极速以图搜图"""
    global _faiss_index
    
    query_bytes = generate_image_embedding(query_image_file)
    if query_bytes is None:
        return []

    query_vec = np.frombuffer(query_bytes, dtype=np.float32).reshape(1, -1)

    if _faiss_index is None or _faiss_index.ntotal == 0:
        build_faiss_index()
        
    if _faiss_index.ntotal == 0:
        return [] 

    # 执行检索
    distances, indices = _faiss_index.search(query_vec, top_k)

    THRESHOLD = 0.45
    target_ids = []
    id_score_map = {}
    
    for i, db_id in enumerate(indices[0]):
        if db_id == -1: 
            continue 
            
        score = float(distances[0][i])
        if score > THRESHOLD:
            target_ids.append(int(db_id))
            id_score_map[int(db_id)] = int(score * 100)

    if not target_ids:
        return []

    objects_dict = queryset.in_bulk(target_ids)
    
    results = []
    for obj_id in target_ids:
        if obj_id in objects_dict:
            obj = objects_dict[obj_id]
            obj.similarity_score = id_score_map[obj_id]
            results.append(obj)
            
    return results