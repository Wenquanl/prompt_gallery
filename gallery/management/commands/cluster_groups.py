from django.core.management.base import BaseCommand
from gallery.models import PromptGroup
import difflib
import uuid

class Command(BaseCommand):
    help = '【修复版】重新计算所有组的 Group ID，解决同ID问题'

    def handle(self, *args, **options):
        # 获取所有数据
        groups = list(PromptGroup.objects.all().order_by('id'))
        total = len(groups)
        self.stdout.write(f"正在重置并聚类 {total} 个提示词组...")

        clusters = [] 
        
        # 统计计数
        count_new_cluster = 0
        count_merged = 0

        for i, group in enumerate(groups):
            # 【关键修正】只提取正向提示词进行比对
            current_content = (group.prompt_text or "").strip().lower()
            
            found_cluster = None
            best_match_score = 0
            
            # 尝试在已有的簇中找相似的
            # (为了性能，只倒序对比最近的 50 个簇，太久远的就不管了)
            for cluster in reversed(clusters[-50:]):
                c_text = cluster['content']
                
                # 如果提示词太短，或者长度差异太大，跳过
                if len(current_content) < 5 or abs(len(current_content) - len(c_text)) > len(c_text) * 0.4:
                    continue

                ratio = difflib.SequenceMatcher(None, current_content, c_text).ratio()
                
                if ratio > 0.85 and ratio > best_match_score:
                    best_match_score = ratio
                    found_cluster = cluster
            
            if found_cluster:
                # 找到了相似的，沿用它的 group_id
                group.group_id = found_cluster['group_id']
                count_merged += 1
            else:
                # 没找到相似的，或者这是第一条
                # 【致命修正】必须生成一个新的 UUID！不能用 group.group_id (因为旧数据里它可能全是重复的)
                new_uid = uuid.uuid4()
                group.group_id = new_uid
                
                # 记录这个新簇
                clusters.append({
                    'group_id': new_uid,
                    'content': current_content
                })
                count_new_cluster += 1
            
            # 保存
            group.save(update_fields=['group_id'])
            
            if i % 100 == 0:
                self.stdout.write(f"处理进度: {i}/{total} ...")

        self.stdout.write(self.style.SUCCESS(
            f"修复完成！\n"
            f"- 总记录数: {total}\n"
            f"- 独立家族数 (首页将显示): {count_new_cluster}\n"
            f"- 被折叠的变体数: {count_merged}"
        ))