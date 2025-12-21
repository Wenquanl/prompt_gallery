import numpy as np
from PIL import Image
from sentence_transformers import SentenceTransformer
import torch

# 单例模式加载模型，防止每次请求都重新加载
_model = None

def get_model():
    global _model
    if _model is None:
        print("正在加载 CLIP 模型...")
        # 检测是否可用 GPU
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        _model = SentenceTransformer('clip-ViT-B-32', device=device)
        print(f"模型加载完毕，运行在: {device}")
    return _model

def generate_image_embedding(image_path_or_file):
    """
    输入图片路径或文件对象，返回 bytes 格式的向量
    """
    model = get_model()
    try:
        img = Image.open(image_path_or_file)
        # 转换为向量
        embedding = model.encode(img)
        # 归一化 (方便后续计算余弦相似度)
        embedding = embedding / np.linalg.norm(embedding)
        # 转为 bytes 存储到数据库
        return embedding.astype(np.float32).tobytes()
    except Exception as e:
        print(f"生成向量失败: {e}")
        return None

def search_similar_images(query_image_file, queryset, top_k=50):
    """
    在给定的 queryset 中搜索与 query_image_file 最相似的图片
    返回结果列表，且每个对象附带 .similarity_score 属性 (0-100)
    """
    # 1. 计算查询图的向量
    query_bytes = generate_image_embedding(query_image_file)
    if query_bytes is None:
        return []

    # 还原为 numpy 数组
    query_vec = np.frombuffer(query_bytes, dtype=np.float32)

    # 2. 取出数据库中所有的向量
    valid_items = []
    vectors = []
    
    for item in queryset:
        if item.feature_vector:
            valid_items.append(item)
            vec = np.frombuffer(item.feature_vector, dtype=np.float32)
            vectors.append(vec)
    
    if not vectors:
        return []

    # 3. 批量计算相似度 (矩阵运算)
    matrix = np.vstack(vectors) # Shape: (N, 512)
    scores = np.dot(matrix, query_vec) # Shape: (N,)

    # 4. 排序并取 Top K
    top_indices = np.argsort(scores)[::-1][:top_k]

    results = []
    
    # 【核心调整】阈值设定为 0.45 (45%)
    # CLIP模型下，完全不相关的图片相似度通常在 0.15-0.25 之间
    # 0.45 是一个比较安全的过滤线，能筛掉大部分无关图片
    THRESHOLD = 0.45 

    for idx in top_indices:
        score = float(scores[idx])
        if score > THRESHOLD: 
            item = valid_items[idx]
            # 【核心】把分数挂载到对象上，方便前端显示 (转为整数百分比)
            item.similarity_score = int(score * 100)
            results.append(item)
    
    return results