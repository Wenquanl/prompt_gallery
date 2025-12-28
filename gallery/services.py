import os
import shutil
import hashlib
import threading
import uuid
from django.conf import settings
from django.core.files.base import ContentFile
from .models import ImageItem
from .ai_utils import generate_image_embedding

def is_valid_uuid(val):
    """校验是否为合法的 UUID 字符串"""
    try:
        uuid.UUID(str(val))
        return True
    except ValueError:
        return False

def get_temp_dir(batch_id):
    """
    获取临时文件存储路径 (带安全性校验)
    防止 batch_id 包含 '../' 等路径遍历字符
    """
    if not batch_id or not is_valid_uuid(batch_id):
        # 如果 ID 非法，返回一个不存在的安全路径，确保后续 exists() 检查失败
        return os.path.join(settings.MEDIA_ROOT, 'temp_uploads', 'invalid_id_security_block')
    
    return os.path.join(settings.MEDIA_ROOT, 'temp_uploads', batch_id)

def calculate_file_hash(file_obj):
    """计算文件的 MD5 哈希值"""
    md5 = hashlib.md5()
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)
    for chunk in file_obj.chunks():
        md5.update(chunk)
    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)
    return md5.hexdigest()

def process_images_background(image_ids):
    """后台任务：计算哈希与向量"""
    if not image_ids:
        return
    
    # 重新引入 ImageItem 防止循环引用
    # (在函数内部引用是安全的)
    from .models import ImageItem

    print(f"Start background processing for {len(image_ids)} images...")
    for img_id in image_ids:
        try:
            img_item = ImageItem.objects.get(id=img_id)
            save_needed = False
            
            if not img_item.image_hash and img_item.image:
                try:
                    # 直接读取文件计算，不依赖 request.FILES
                    with open(img_item.image.path, 'rb') as f:
                        hasher = hashlib.md5()
                        for chunk in iter(lambda: f.read(4096), b""):
                            hasher.update(chunk)
                        img_item.image_hash = hasher.hexdigest()
                        save_needed = True
                except Exception as e:
                    print(f"Hash calc error {img_id}: {e}")

            if img_item.feature_vector is None and img_item.image:
                try:
                    embedding_bytes = generate_image_embedding(img_item.image.path)
                    if embedding_bytes:
                        img_item.feature_vector = embedding_bytes
                        save_needed = True
                except Exception as e:
                    print(f"Embedding error {img_id}: {e}")
            
            if save_needed:
                img_item.save(update_fields=['image_hash', 'feature_vector'])
            
        except ImageItem.DoesNotExist:
            continue
        except Exception as e:
            print(f"Background task error {img_id}: {e}")

def trigger_background_processing(image_ids):
    """启动后台线程"""
    if image_ids:
        threading.Thread(
            target=process_images_background, 
            args=(image_ids,)
        ).start()

def confirm_upload_images(batch_id, file_names, group):
    """
    【安全封装】将临时文件移动到正式目录并创建数据库记录
    1. 校验 batch_id 安全性
    2. 校验 file_name 安全性 (防止路径遍历)
    3. 返回创建的 ImageItem ID 列表
    """
    temp_dir = get_temp_dir(batch_id)
    if not os.path.exists(temp_dir):
        return []

    created_ids = []
    
    # 如果没有指定文件，则处理目录下所有文件
    if not file_names:
        file_names = os.listdir(temp_dir)

    for file_name in file_names:
        # 安全性过滤：仅取文件名部分，去除路径
        safe_name = os.path.basename(file_name)
        src_path = os.path.join(temp_dir, safe_name)
        
        if os.path.exists(src_path) and os.path.isfile(src_path):
            # 使用 Django File 对象保存，触发 models.py 中的 unique_file_path 逻辑
            # 这样既保证了文件名唯一，又防止了覆盖
            try:
                with open(src_path, 'rb') as f:
                    # 使用 ContentFile 包装文件流
                    content = ContentFile(f.read())
                    # 文件名可以使用原始扩展名，models.py 会重命名为 UUID
                    img_item = ImageItem(group=group)
                    img_item.image.save(safe_name, content, save=True)
                    created_ids.append(img_item.id)
            except Exception as e:
                print(f"Error moving file {safe_name}: {e}")

    # 清理临时目录
    try:
        shutil.rmtree(temp_dir)
    except Exception as e:
        print(f"Error cleaning temp dir: {e}")

    return created_ids