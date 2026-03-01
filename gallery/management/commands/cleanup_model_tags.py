from django.core.management.base import BaseCommand
from django.db import transaction
from gallery.models import Tag, AIModel, PromptGroup

class Command(BaseCommand):
    help = '从普通标签(Tag)中移除并删除所有已在 AIModel 中定义的模型标签'

    def handle(self, *args, **options):
        # 1. 获取所有已定义的模型名称
        model_names = list(AIModel.objects.values_list('name', flat=True))
        
        if not model_names:
            self.stdout.write(self.style.WARNING("AIModel 表中没有数据，取消清理。"))
            return

        with transaction.atomic():
            # 2. 找到名称匹配模型的标签
            tags_to_delete = Tag.objects.filter(name__in=model_names)
            tag_count = tags_to_delete.count()
            
            if tag_count == 0:
                self.stdout.write(self.style.SUCCESS("没有发现需要清理的模型标签。"))
                return

            # 3. 统计受影响的作品数
            affected_groups = PromptGroup.objects.filter(tags__in=tags_to_delete).distinct().count()

            # 4. 执行删除 (Django 会自动处理 ManyToMany 的中间表解绑)
            tags_to_delete.delete()

            self.stdout.write(self.style.SUCCESS(
                f'清理完成：\n'
                f'- 删除了 {tag_count} 个模型标签名\n'
                f'- 解除了 {affected_groups} 个作品组的冗余标签关联'
            ))

# 运行命令：python manage.py cleanup_model_tags 