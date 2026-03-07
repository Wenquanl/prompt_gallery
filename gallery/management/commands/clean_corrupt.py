import os
from PIL import Image
from django.core.management.base import BaseCommand
from gallery.models import ImageItem, ReferenceItem

class Command(BaseCommand):
    help = '扫描并清理数据库中损坏的图片（解决 UnidentifiedImageError 导致首页崩溃的问题）'

    def handle(self, *args, **options):
        deleted_count = 0
        
        # 遍历生成的图和参考图
        for Model in [ImageItem, ReferenceItem]:
            for item in Model.objects.all():
                # 如果是视频，或者是没有实体的记录，则跳过
                if not item.image or item.is_video:
                    continue
                
                try:
                    path = item.image.path
                    # 1. 检查文件是否在硬盘上丢失，或者是否为 0 字节
                    if not os.path.exists(path) or os.path.getsize(path) == 0:
                        raise Exception("文件丢失或大小为0")
                    
                    # 2. 尝试用底层的图像处理库去读取它的头部信息
                    with Image.open(path) as img:
                        img.verify() # 严格验证它是不是一张合法的图片
                        
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"🧹 已清理损坏数据 -> {Model.__name__} (ID: {item.id}) | 原因: {e}"))
                    
                    # 发现损坏，安全删除数据库里的这条记录
                    item.delete()
                    deleted_count += 1
                    
        self.stdout.write(self.style.SUCCESS(f'\n🎉 扫描清理完成！共揪出并移除了 {deleted_count} 个损坏的假图片。快去刷新首页吧！'))