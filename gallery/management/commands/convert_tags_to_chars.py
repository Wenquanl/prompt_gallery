from django.core.management.base import BaseCommand
from django.db import transaction
from gallery.models import Tag, Character, PromptGroup

class Command(BaseCommand):
    help = '将指定的普通标签批量转换为人物标签'

    def add_arguments(self, parser):
        # 允许通过命令行输入一个或多个标签名
        parser.add_argument('tag_names', nargs='+', type=str, help='要转换的标签名称列表')

    def handle(self, *args, **options):
        tag_names = options['tag_names']
        converted_count = 0
        
        for name in tag_names:
            name = name.strip()
            with transaction.atomic():
                try:
                    # 1. 查找旧的普通标签
                    tag = Tag.objects.get(name=name)
                    
                    # 2. 创建或获取新的人物标签
                    char, created = Character.objects.get_or_create(name=name)
                    
                    # 3. 找到所有关联了该普通标签的作品组
                    # 注意：根据你的 forms.py 反向关联名为 promptgroup
                    groups = tag.promptgroup_set.all()
                    impacted_count = groups.count()
                    
                    for group in groups:
                        # 4. 建立与人物标签的关联
                        group.characters.add(char)
                        # 5. 移除与普通标签的关联
                        group.tags.remove(tag)
                    
                    # 6. 删除原本的普通标签
                    tag.delete()
                    
                    self.stdout.write(self.style.SUCCESS(f'成功转换 "{name}": 迁移了 {impacted_count} 个作品。'))
                    converted_count += 1
                    
                except Tag.DoesNotExist:
                    self.stdout.write(self.style.WARNING(f'跳过: 标签 "{name}" 在数据库中不存在。'))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'转换 "{name}" 时出错: {str(e)}'))

        self.stdout.write(self.style.SUCCESS(f'\n🎉 批量转换完成，共处理 {converted_count} 个标签。'))