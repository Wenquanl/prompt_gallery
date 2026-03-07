import hashlib
from django.core.management.base import BaseCommand
from gallery.models import ImageItem, ReferenceItem

class Command(BaseCommand):
    help = '强制重新计算全库所有图片和参考图的 MD5 哈希值，修复因算法升级导致的查重失效问题'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING("开始执行全库哈希大清洗... 这可能需要几分钟时间，请勿中断。"))
        
        # 1. 修复生成图 (ImageItem)
        self.stdout.write("\n[1/2] 开始检查和修复 ImageItem (生成作品) 的哈希...")
        self.fix_hashes(ImageItem)
        
        # 2. 修复参考图 (ReferenceItem)
        self.stdout.write("\n[2/2] 开始检查和修复 ReferenceItem (参考图) 的哈希...")
        self.fix_hashes(ReferenceItem)
        
        self.stdout.write(self.style.SUCCESS("\n🎉 全库哈希重新计算完毕！现在所有的图片都有了绝对正确的身份证，查重功能已满血复活！"))

    def fix_hashes(self, ModelClass):
        items = ModelClass.objects.all()
        total = items.count()
        updated = 0
        
        for index, item in enumerate(items, 1):
            if not item.image or not item.image.storage.exists(item.image.name):
                continue
                
            try:
                md5 = hashlib.md5()
                # 强制使用严格的二进制读取模式，绝对不信任以前存的任何数据
                with item.image.open('rb') as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        md5.update(chunk)
                
                real_hash = md5.hexdigest()
                
                # 只要和真实计算出来的不一样，立刻纠正覆盖
                if item.image_hash != real_hash:
                    item.image_hash = real_hash
                    item.save(update_fields=['image_hash'])
                    updated += 1
                    
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  读取文件失败 ID {item.id}: {e}"))
                
            # 每处理 100 张打印一次进度，让你心里有底
            if index % 100 == 0:
                self.stdout.write(f"  进度: {index} / {total}")
                
        self.stdout.write(self.style.SUCCESS(f"-> [{ModelClass.__name__}] 扫描了 {total} 项，成功修正了 {updated} 个错误的哈希值。"))