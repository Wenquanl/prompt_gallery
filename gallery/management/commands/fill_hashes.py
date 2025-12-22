import time
from django.core.management.base import BaseCommand
from gallery.models import ImageItem
from django.db.models import Q

class Command(BaseCommand):
    help = '自动为缺失哈希值的存量图片补充计算 MD5'

    def handle(self, *args, **options):
        # 1. 查找所有没有哈希值的图片
        # 注意：这里同时检查了 空字符串 和 NULL
        items = ImageItem.objects.filter(Q(image_hash='') | Q(image_hash__isnull=True))
        total = items.count()

        self.stdout.write(self.style.SUCCESS(f"👉 正在扫描数据库... 发现 {total} 张图片需要处理"))

        if total == 0:
            self.stdout.write(self.style.SUCCESS("✅ 所有图片都已有哈希值，无需操作。"))
            return

        success_count = 0
        fail_count = 0
        start_time = time.time()

        self.stdout.write("🚀 开始处理...")

        for index, item in enumerate(items):
            try:
                # 检查文件是否存在
                if not item.image:
                    self.stdout.write(self.style.WARNING(f"⚠️ 跳过 ID {item.id}: image 字段为空"))
                    fail_count += 1
                    continue

                # 【显式调用】强制计算哈希，不依赖 save() 的自动判断
                item.calculate_hash()
                
                # 如果计算成功（有值了），再保存
                if item.image_hash:
                    # update_fields 只更新 image_hash 字段，效率更高且不影响其他字段
                    item.save(update_fields=['image_hash'])
                    success_count += 1
                else:
                    self.stdout.write(self.style.ERROR(f"❌ ID {item.id} 计算后哈希仍为空，可能是文件读取失败"))
                    fail_count += 1

            except FileNotFoundError:
                self.stdout.write(self.style.ERROR(f"❌ ID {item.id} 文件未找到: {item.image.name}"))
                fail_count += 1
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"❌ ID {item.id} 未知错误: {e}"))
                fail_count += 1

            # 每处理 50 张打印一次进度
            if (index + 1) % 50 == 0:
                self.stdout.write(f"   ...已处理 {index + 1}/{total}")

        end_time = time.time()
        duration = end_time - start_time

        self.stdout.write(self.style.SUCCESS(f"\n🎉 处理完成！"))
        self.stdout.write(f"   成功: {success_count}")
        self.stdout.write(f"   失败: {fail_count}")
        self.stdout.write(f"   耗时: {duration:.2f} 秒")