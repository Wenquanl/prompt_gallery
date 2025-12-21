import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from gallery.models import ImageItem
from gallery.ai_utils import generate_image_embedding

def process_all():
    items = ImageItem.objects.filter(feature_vector__isnull=True)
    count = items.count()
    print(f"发现 {count} 张图片需要生成向量...")
    
    processed = 0
    for item in items:
        try:
            # 获取图片完整路径
            if item.image and hasattr(item.image, 'path'):
                vec = generate_image_embedding(item.image.path)
                if vec:
                    item.feature_vector = vec
                    item.save()
                    processed += 1
                    if processed % 10 == 0:
                        print(f"进度: {processed}/{count}")
        except Exception as e:
            print(f"处理图片 ID {item.id} 出错: {e}")

    print("处理完成！")

if __name__ == '__main__':
    process_all()