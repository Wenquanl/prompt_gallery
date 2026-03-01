import numpy as np
from PIL import Image
from sentence_transformers import SentenceTransformer
import torch
import os
import cv2  # 【新增】引入 OpenCV 处理视频
import tempfile # 【新增】处理上传的视频流
from transformers import AutoModelForCausalLM, AutoTokenizer

# 全局变量存储模型 (单例模式)
_model = None
_text_model = None
_text_tokenizer = None

def load_model_on_startup():
    """
    系统启动时预加载模型，由 apps.py 调用
    """
    global _model, _text_model, _text_tokenizer
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    if _model is None:
        print(">>> [AI核心] 正在预加载 CLIP 模型 (首次运行可能需要下载)...")
        try:
            # 检测是否可用 GPU
            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            _model = SentenceTransformer('clip-ViT-B-32', device=device)
            print(f">>> [AI核心] CLIP 模型加载完毕，运行设备: {device}")
        except Exception as e:
            print(f">>> [AI核心] ❌ 模型加载失败: {e}")
    # 【新增】加载用于生成标题的轻量级本地 LLM
    if _text_model is None:
        print(">>> [AI核心] 正在预加载本地文本大模型 (用于标题智能概括)...")
        try:
            model_id = "Qwen/Qwen2.5-0.5B-Instruct"
            _text_tokenizer = AutoTokenizer.from_pretrained(model_id)
            dtype = torch.float16 if device == 'cuda' else torch.float32
            _text_model = AutoModelForCausalLM.from_pretrained(
                model_id, 
                torch_dtype=dtype,
                low_cpu_mem_usage=True
            ).to(device)
            print(f">>> [AI核心] 本地文本大模型加载完毕！")
        except Exception as e:
            print(f">>> [AI核心] ❌ 文本大模型加载失败: {e}")

def generate_title_with_local_llm(prompt_text):
    """
    调用本地加载的大模型进行提示词概括
    """
    global _text_model, _text_tokenizer
    
    if _text_model is None or _text_tokenizer is None:
        return None

    try:
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        
        system_prompt = """你是一个专业的AI绘画策展人。请为下面的绘画提示词创作一个简短、有美感的中文作品标题。
                            要求：
                            1. 敏锐捕捉核心主体（如具体的人物角色、服装打扮）和环境意境；
                            2. 坚决忽略所有关于画质、镜头、光影和渲染的参数（如3D CG、超写实摄影、胶片、8k、LOMO等）；
                            3. 必须是纯中文，高度凝练，严格控制在15个字以内；
                            4. 直接输出最终的标题，绝对不要带任何标点符号、引号或多余的解释。"""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"提示词：{prompt_text}"}
        ]
        
        text = _text_tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        model_inputs = _text_tokenizer([text], return_tensors="pt").to(device)

        generated_ids = _text_model.generate(
            model_inputs.input_ids,
            max_new_tokens=40,      
            temperature=0.3,        
            repetition_penalty=1.1, 
            do_sample=True
        )
        
        generated_ids = [
            output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        response = _text_tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        
        # 清理可能产生的意外标点符号
        title = response.strip().strip('"').strip('”').strip('“').strip('《').strip('》')
        
        if title and len(title) <= 30:
            return title
        elif len(title) > 30:
            return title[:28] + "..."
            
    except Exception as e:
        print(f"本地大模型生成标题时发生错误: {e}")
        return None

def get_model():
    """
    获取模型实例，如果因某种原因未在启动时加载，则在此处惰性加载
    """
    global _model
    if _model is None:
        load_model_on_startup()
    return _model

def generate_image_embedding(image_path_or_file):
    """
    输入图片路径或文件对象，返回 bytes 格式的向量
    支持：图片文件、视频文件 (自动提取第一帧)
    """
    model = get_model()
    if model is None:
        return None
        
    temp_video_path = None
    
    try:
        img = None
        is_video = False
        file_path = ""

        # 1. 判断是否为视频
        if isinstance(image_path_or_file, str):
            # 情况A: 传入的是文件路径
            file_path = image_path_or_file
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']:
                is_video = True
        elif hasattr(image_path_or_file, 'name'):
            # 情况B: 传入的是上传的文件对象
            ext = os.path.splitext(image_path_or_file.name)[1].lower()
            if ext in ['.mp4', '.mov', '.avi', '.webm', '.mkv']:
                is_video = True
                # OpenCV 无法直接读取内存文件流，需写入临时文件
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    if hasattr(image_path_or_file, 'seek'): image_path_or_file.seek(0)
                    tmp.write(image_path_or_file.read())
                    temp_video_path = tmp.name
                    file_path = tmp.name

        # 2. 如果是视频，提取第一帧
        if is_video:
            cap = cv2.VideoCapture(file_path)
            ret, frame = cap.read()
            cap.release()
            
            if ret:
                # OpenCV 默认是 BGR，CLIP 需要 RGB
                frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(frame)
        
        # 3. 如果不是视频或提取失败，尝试作为普通图片打开
        if img is None:
            img = Image.open(image_path_or_file)
        
        # 4. 转换为向量
        embedding = model.encode(img)
        
        # 归一化 (方便后续计算余弦相似度)
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
            
        # 转为 bytes 存储到数据库
        return embedding.astype(np.float32).tobytes()
        
    except Exception as e:
        # print(f"生成向量失败: {e}") # 生产环境可取消注释
        return None
    finally:
        # 清理临时文件
        if temp_video_path and os.path.exists(temp_video_path):
            try:
                os.remove(temp_video_path)
            except:
                pass

def search_similar_images(query_image_file, queryset, top_k=50):
    """
    高性能向量检索优化版：
    1. 使用 values_list 仅读取 id 和 vector，避免实例化 Model 对象，极大降低内存消耗
    2. 使用 numpy 矩阵运算代替循环，提升计算速度
    """
    # 1. 计算查询图的向量
    query_bytes = generate_image_embedding(query_image_file)
    if query_bytes is None:
        return []

    # 还原为 numpy 数组 (Shape: 512,)
    query_vec = np.frombuffer(query_bytes, dtype=np.float32)

    # 2. 仅从数据库提取 ID 和 BinaryVector
    # exclude(feature_vector__isnull=True) 确保只取有向量的数据
    data_list = list(queryset.exclude(feature_vector__isnull=True).values_list('id', 'feature_vector'))
    
    if not data_list:
        return []

    # 3. 构建计算矩阵
    ids = [item[0] for item in data_list]
    
    # 批量将 bytes 转换为 numpy 数组
    try:
        # 假设向量维度是 512 (CLIP Base)
        vectors = np.array([np.frombuffer(item[1], dtype=np.float32) for item in data_list])
    except Exception as e:
        print(f"向量数据解析失败: {e}")
        return []

    # 4. 矩阵运算计算相似度 (余弦相似度)
    # vectors: (N, 512) dot query_vec: (512,) -> scores: (N,)
    # 因为入库时已归一化，此处直接点积即为余弦相似度
    scores = np.dot(vectors, query_vec)

    # 5. 获取 Top K 的索引
    # argsort 是从小到大，[::-1] 反转，[:k] 取前 k 个
    k = min(top_k, len(scores))
    top_indices = np.argsort(scores)[::-1][:k]

    results = []
    
    # 阈值设定 (0.45 约为 45% 相似度，低于此值的通常不相关)
    THRESHOLD = 0.45
    
    # 收集符合条件的 ID 和 分数
    target_ids = []
    id_score_map = {} # id -> score (0-100)

    for idx in top_indices:
        score = float(scores[idx])
        if score > THRESHOLD:
            obj_id = ids[idx]
            target_ids.append(obj_id)
            id_score_map[obj_id] = int(score * 100)
    
    if not target_ids:
        return []

    # 6. 批量获取数据库完整对象 (使用 in_bulk 减少查询次数)
    objects_dict = queryset.in_bulk(target_ids)
    
    # 按照 target_ids 的排序顺序重组列表，并将分数挂载到对象上
    for obj_id in target_ids:
        if obj_id in objects_dict:
            obj = objects_dict[obj_id]
            obj.similarity_score = id_score_map[obj_id]
            results.append(obj)
            
    return results