import os
import re
from datetime import datetime
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.core.files import File
from django.utils import timezone
from gallery.models import PromptGroup, ImageItem, ReferenceItem

class Command(BaseCommand):
    help = '从 Google Takeout 导入 Gemini 数据（仅提取包含生成图片的对话）'

    def add_arguments(self, parser):
        parser.add_argument('html_file', type=str, help='Gemini.html 文件的绝对或相对路径')

    def handle(self, *args, **options):
        html_file_path = options['html_file']
        
        if not os.path.exists(html_file_path):
            self.stdout.write(self.style.ERROR(f'找不到文件: {html_file_path}'))
            return

        base_dir = os.path.dirname(os.path.abspath(html_file_path))

        self.stdout.write(f'正在解析: {html_file_path} ...')
        with open(html_file_path, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')

        blocks = soup.find_all('div', class_='outer-cell')
        success_count = 0
        skipped_count = 0

        for block in blocks:
            content_div = block.find('div', class_='content-cell mdl-cell mdl-cell--6-col mdl-typography--body-1')
            if not content_div: 
                continue

            # --- 1. 核心过滤逻辑：先查找是否有生成的图片 ---
            content_imgs = content_div.find_all('img')
            valid_gen_imgs = []
            
            for img in content_imgs:
                # 排除掉作为参考图上传的图片 (class 包含 image-preview)
                if 'src' in img.attrs and 'image-preview' not in img.get('class', []):
                    gen_img_name = img['src']
                    gen_img_path = os.path.join(base_dir, gen_img_name)
                    # 确保图片文件在本地真的存在
                    if os.path.exists(gen_img_path):
                        valid_gen_imgs.append(gen_img_path)
            
            # 如果这个对话块里没有找到任何实际存在的生成图片，说明是纯文本对话，直接跳过！
            if not valid_gen_imgs:
                skipped_count += 1
                continue

            # --- 2. 如果有图片，再提取文本和时间 ---
            strings = list(content_div.stripped_strings)
            prompt_text = ""
            date_str = ""

            for s in strings:
                if s.startswith('Prompted'):
                    prompt_text = s.replace('Prompted\xa0', '').replace('Prompted ', '').strip()
                elif 'GMT' in s or '年' in s and '月' in s:
                    date_str = s

            if not prompt_text:
                continue

            title = prompt_text[:30] + '...' if len(prompt_text) > 30 else prompt_text

            # --- 3. 创建提示词组 (PromptGroup) ---
            group = PromptGroup.objects.create(
                title=title,
                prompt_text=prompt_text,
                provider='gemini_web', 
            )

            # 解析并修改创建时间
            if date_str:
                match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日 (\d{2}):(\d{2}):(\d{2})', date_str)
                if match:
                    year, month, day, hour, minute, second = map(int, match.groups())
                    dt = datetime(year, month, day, hour, minute, second)
                    aware_dt = timezone.make_aware(dt, timezone.get_default_timezone())
                    PromptGroup.objects.filter(id=group.id).update(created_at=aware_dt)

            # --- 4. 处理参考图 (如果有) ---
            preview_img = block.find('img', class_='image-preview')
            if preview_img and 'src' in preview_img.attrs:
                ref_img_name = preview_img['src']
                ref_img_path = os.path.join(base_dir, ref_img_name)
                
                if os.path.exists(ref_img_path):
                    with open(ref_img_path, 'rb') as img_f:
                        ref_item = ReferenceItem(group=group)
                        ref_item.image.save(ref_img_name, File(img_f), save=True)

            # --- 5. 处理并保存刚才找到的生成图片 ---
            for img_path in valid_gen_imgs:
                img_name = os.path.basename(img_path)
                with open(img_path, 'rb') as img_f:
                    gen_item = ImageItem(group=group)
                    gen_item.image.save(img_name, File(img_f), save=True)
                    
                    # 设置第一张图为封面
                    if not group.cover_image:
                        group.cover_image = gen_item
                        group.save()

            success_count += 1
            self.stdout.write(f'已导入 [包含图片]: {title}')

        self.stdout.write(self.style.SUCCESS(
            f'\n🎉 导入完成！\n'
            f'✅ 成功导入: {success_count} 组 (纯图片生成)\n'
            f'⏭️ 已自动跳过: {skipped_count} 组 (纯文本对话或图片已丢失)'
        ))