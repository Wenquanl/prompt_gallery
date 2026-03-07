import os
import hashlib
from collections import defaultdict
from django.core.management.base import BaseCommand
from django.conf import settings
from gallery.models import ReferenceItem

class Command(BaseCommand):
    help = '清理历史重复的参考图文件 (强制重新计算哈希版)'

    def handle(self, *args, **options):
        self.stdout.write("开始扫描全库参考图并建立哈希分组 (强制重新计算真实哈希)...")
        
        all_refs = ReferenceItem.objects.all()
        total_count = all_refs.count()
        self.stdout.write(f"数据库中共有 {total_count} 条参考图记录。")
        
        hash_groups = defaultdict(list)
        
        # 1. 强制重新计算所有文件的真实哈希，绝对不信任数据库里的旧数据
        for ref in all_refs:
            if not ref.image or not ref.image.storage.exists(ref.image.name):
                continue
                
            try:
                md5 = hashlib.md5()
                # 使用标准的二进制读取模式，确保哈希 100% 准确
                with ref.image.open('rb') as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        md5.update(chunk)
                real_hash = md5.hexdigest()
                
                # 如果发现数据库里的旧哈希是错的，顺手纠正它
                if ref.image_hash != real_hash:
                    ref.image_hash = real_hash
                    ref.save(update_fields=['image_hash'])
                    
                hash_groups[real_hash].append(ref)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"  无法读取文件 {ref.image.name}: {e}"))
        
        self.stdout.write(f"扫描完毕！这 {total_count} 条记录中，实际包含 {len(hash_groups)} 个底层二进制完全不同的文件。")
        
        updated_db_count = 0
        files_to_delete = set()

        # 2. 找出重复项，重定向数据库记录
        for img_hash, refs in hash_groups.items():
            if len(refs) <= 1:
                continue 
                
            # 选出一个“原版老大” (优先选文件名里没有 copy_ 的)
            master_ref = None
            for r in refs:
                if 'copy_' not in r.image.name:
                    master_ref = r
                    break
            if not master_ref:
                master_ref = refs[0]
                
            master_path = master_ref.image.name
            
            # 将同组的其它小弟记录，全部改写路径指向老大
            for r in refs:
                if r.id != master_ref.id and r.image.name != master_path:
                    old_path = r.image.name
                    files_to_delete.add(old_path) 
                    
                    r.image.name = master_path
                    r.save(update_fields=['image'])
                    updated_db_count += 1
                    self.stdout.write(f"  [重定向] 记录 ID {r.id} 已指向 -> {master_path}")

        self.stdout.write(self.style.SUCCESS(f"数据库记录修改完成，共更新了 {updated_db_count} 条。"))
        
        # 3. 强删废弃文件
        deleted_files_count = 0
        if files_to_delete:
            self.stdout.write("================================")
            self.stdout.write("开始清理废弃的物理文件 (释放硬盘空间)...")
            for old_path in files_to_delete:
                full_path = os.path.join(settings.MEDIA_ROOT, old_path)
                if os.path.exists(full_path):
                    try:
                        os.remove(full_path)
                        deleted_files_count += 1
                        self.stdout.write(f"  [清理成功] 已删除: {old_path}")
                    except Exception as e:
                        self.stdout.write(self.style.WARNING(f"  [清理失败] 无法删除 {old_path}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"\n🎉 彻底去重完成！重定向了 {updated_db_count} 条记录，腾出了 {deleted_files_count} 个文件的硬盘空间。"))