import os
import hashlib
from django.core.management.base import BaseCommand
from gallery.models import ReferenceItem

class Command(BaseCommand):
    help = '清理历史重复的参考图文件，让它们指向同一个物理文件'

    def handle(self, *args, **options):
        self.stdout.write("开始扫描并去重参考图...")
        
        all_refs = ReferenceItem.objects.all()
        hash_to_path = {}
        deleted_files_count = 0
        updated_refs_count = 0

        # 第一遍：确保所有文件都有哈希，并建立 哈希->最早物理文件 的映射
        for ref in all_refs:
            if not ref.image or not ref.image.storage.exists(ref.image.name):
                continue
                
            if not ref.image_hash:
                ref.calculate_hash()
                if ref.image_hash:
                    ref.save(update_fields=['image_hash'])
            
            if ref.image_hash:
                # 记录最早（ID最小）或者看起来像原文件（没有 copy_ 前缀）的路径
                current_path = ref.image.name
                
                if ref.image_hash not in hash_to_path:
                    hash_to_path[ref.image_hash] = current_path
                else:
                    # 如果当前路径看起来更像“原版”（没有 copy_），优先使用当前路径作为主路径
                    existing_path = hash_to_path[ref.image_hash]
                    if 'copy_' in existing_path and 'copy_' not in current_path:
                        hash_to_path[ref.image_hash] = current_path

        # 第二遍：将所有重复的 ReferenceItem 指向主物理文件，并删除多余文件
        for ref in all_refs:
            if not ref.image_hash or ref.image_hash not in hash_to_path:
                continue
                
            master_path = hash_to_path[ref.image_hash]
            current_path = ref.image.name
            
            if current_path != master_path:
                # 【新增】：在尝试删除之前，强制关闭当前对象持有的文件句柄
                if ref.image and not ref.image.closed:
                    ref.image.close()
                    
                # 1. 尝试删除多余的物理文件
                try:
                    if ref.image.storage.exists(current_path):
                        ref.image.storage.delete(current_path)
                        deleted_files_count += 1
                        self.stdout.write(f"  删除了重复文件: {current_path}")
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"  删除文件失败 {current_path}: {e}"))
                
                # 2. 将数据库记录指向主文件
                ref.image.name = master_path
                ref.save(update_fields=['image'])
                updated_refs_count += 1
                self.stdout.write(f"  重定向数据库记录 ID {ref.id} -> {master_path}")

        self.stdout.write(self.style.SUCCESS(f"去重完成！清理了 {deleted_files_count} 个物理文件，更新了 {updated_refs_count} 条数据库记录。"))