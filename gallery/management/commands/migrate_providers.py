# gallery/management/commands/migrate_providers.py
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from gallery.models import PromptGroup, AIModel, Tag

class Command(BaseCommand):
    help = '批量清洗历史模型标签，分离模型名称与生成渠道'

    def handle(self, *args, **kwargs):
        self.stdout.write("🚀 开始清洗历史模型数据...")

        # 1. 基础后缀映射字典 (统一转小写进行匹配)
        provider_mapping = {
            'fal': 'fal_ai',
            'midjourney': 'midjourney',
            'mj': 'midjourney',
            'webui': 'webui',
            'comfyui': 'comfyui',
            'local': 'local',
            'gemini': 'gemini_web',  # <--- 新增：只要后缀带 gemini，就归属为网页/APP渠道
        }

        with transaction.atomic():
            groups = PromptGroup.objects.all()
            updated_count = 0
            
            for group in groups:
                old_model_info = group.model_info or ""
                if not old_model_info:
                    continue
                
                # 使用正则匹配：提取 "模型名 (渠道名)" 或者 "模型名(渠道名)"
                # 例如："Imagen 3 (Gemini)" -> name="Imagen 3", provider_raw="gemini"
                match = re.search(r'^(.*?)\s*[\(（](.*?)[\)）]$', old_model_info)
                
                if match:
                    clean_model_name = match.group(1).strip()
                    provider_raw = match.group(2).strip().lower()
                    
                    # === 智能推断 Provider ===
                    new_provider = 'other' # 默认保底为 other
                    
                    # 优先尝试从基础字典中直接命中
                    for key, val in provider_mapping.items():
                        if key in provider_raw:
                            new_provider = val
                            break
                    
                    # 如果后缀是“官方”，需要根据模型名称来二次判断归属 (覆盖上面默认的 other)
                    if '官方' in provider_raw or 'official' in provider_raw:
                        model_name_lower = clean_model_name.lower()
                        
                        # 火山引擎的官方模型 (如 Seedream)
                        if 'seedream' in model_name_lower:
                            new_provider = 'volcengine'
                            
                        # Google AI 的官方 API 模型 (如 Nano Banana)
                        elif 'nano banana' in model_name_lower or 'gemini' in model_name_lower:
                            new_provider = 'google_ai'
                            
                        else:
                            new_provider = 'other'

                    # === 更新 PromptGroup 记录 ===
                    group.model_info = clean_model_name
                    group.provider = new_provider
                    group.save(update_fields=['model_info', 'provider'])
                    updated_count += 1

                    # === 同步清理 Tags 表 ===
                    # 找到旧的带括号的标签
                    old_tags = Tag.objects.filter(name=old_model_info)
                    # 确保存在干净名称的新标签
                    clean_tag, _ = Tag.objects.get_or_create(name=clean_model_name)
                    
                    # 将该作品上的旧标签替换为干净标签
                    for old_tag in old_tags:
                        group.tags.add(clean_tag)
                        group.tags.remove(old_tag)
                        
            # === 清理 AIModel 表 ===
            # 将旧的带括号的 AIModel 删除，并确保干净的模型名存在于侧边栏/顶部
            old_ai_models = AIModel.objects.filter(name__iregex=r'[\(（].*?[\)）]')
            for old_am in old_ai_models:
                clean_name = re.sub(r'\s*[\(（].*?[\)）]$', '', old_am.name).strip()
                AIModel.objects.get_or_create(name=clean_name)
                old_am.delete()

            # 清理孤立的旧 Tag (没有被任何 PromptGroup 使用的废弃标签)
            Tag.objects.filter(promptgroup__isnull=True).delete()

        self.stdout.write(self.style.SUCCESS(f"✅ 清洗完成！共更新了 {updated_count} 张卡片。"))