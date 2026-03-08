import os
import django

# 初始化 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings') # 根据你的项目名调整 core
django.setup()

import meilisearch
from gallery.models import PromptGroup

def push_all_to_meilisearch():
    client = meilisearch.Client('http://127.0.0.1:7700', 'dq49aaqs-RYHbIfKGMOFJRrfco3jP-0Ubj4gcX9caBc')
    docs = []
    
    # 预加载标签和人物，防止这里引发 N+1 查询
    groups = PromptGroup.objects.prefetch_related('tags', 'characters').all()
    
    print(f"正在读取 {groups.count()} 条卡片数据...")
    for g in groups:
        tags_list = [t.name for t in g.tags.all()]
        chars_list = [c.name for c in g.characters.all()] if hasattr(g, 'characters') else []
        
        docs.append({
            'id': g.id,
            'title': g.title,
            'prompt_text': g.prompt_text or '',
            'prompt_text_zh': g.prompt_text_zh or '',
            'model_info': g.model_info or '',
            'tags': tags_list,
            'characters': chars_list,
        })
        
    print("开始向 Meilisearch 推送数据...")
    # 批量上传，速度极快
    task = client.index('prompts').add_documents_in_batches(docs, batch_size=2000)
    print("✅ 推送完成！引擎会在后台数秒内建立好倒排索引。")

if __name__ == "__main__":
    push_all_to_meilisearch()