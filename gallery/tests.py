from io import BytesIO
from datetime import timedelta
import os
import shutil
import tempfile
import json
from unittest.mock import Mock, mock_open, patch

import numpy as np
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .ai_providers import get_ai_provider
from .models import AIModel, GPTImageConversation, GPTImageConversationTurn, ImageItem, PromptGroup, Tag
from .prompt_mediation import mediate_gpt_image_prompt
from .views import _order_images_by_similarity


class PromptGroupPromptStorageTests(TestCase):
	def test_save_builds_prompts_and_searchable_cache_from_legacy_fields(self):
		group = PromptGroup.objects.create(
			title='统一提示词',
			prompt_text='first prompt',
			prompt_text_zh='second prompt',
			negative_prompt='third prompt',
		)

		group.refresh_from_db()
		self.assertEqual(
			[item['text'] for item in group.prompts],
			['first prompt', 'second prompt', 'third prompt']
		)
		self.assertEqual(group.searchable_prompts, 'first prompt\nsecond prompt\nthird prompt')

	def test_save_syncs_legacy_fields_from_prompts(self):
		group = PromptGroup.objects.create(
			title='统一提示词',
			prompt_text='',
			prompts=[
				{'text': '提示词A'},
				{'text': '提示词B'},
				{'text': '提示词C'},
				{'text': '提示词D'},
			],
		)

		group.refresh_from_db()
		self.assertEqual(group.prompt_text, '提示词A')
		self.assertEqual(group.prompt_text_zh, '提示词B')
		self.assertEqual(group.negative_prompt, '提示词C')
		self.assertEqual(group.searchable_prompts, '提示词A\n提示词B\n提示词C\n提示词D')

	def test_update_group_prompts_accepts_unified_prompt_array(self):
		group = PromptGroup.objects.create(
			title='待更新',
			prompt_text='旧提示词1',
			prompt_text_zh='旧提示词2',
		)

		response = self.client.post(
			reverse('update_group_prompts', args=[group.pk]),
			data=json.dumps({
				'prompts': [
					{'text': '新提示词1'},
					{'text': '新提示词2'},
					{'text': '新提示词3'},
				]
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		group.refresh_from_db()
		self.assertEqual([item['text'] for item in group.prompts], ['新提示词1', '新提示词2', '新提示词3'])
		self.assertEqual(group.prompt_text, '新提示词1')
		self.assertEqual(group.prompt_text_zh, '新提示词2')
		self.assertEqual(group.negative_prompt, '新提示词3')
		self.assertEqual(group.searchable_prompts, '新提示词1\n新提示词2\n新提示词3')

	def test_update_group_prompts_rejects_duplicate_prompt_items(self):
		group = PromptGroup.objects.create(
			title='禁止重复',
			prompt_text='旧提示词1',
		)

		response = self.client.post(
			reverse('update_group_prompts', args=[group.pk]),
			data=json.dumps({
				'prompts': [
					{'text': '重复提示词'},
					{'text': '  重复提示词  '},
				]
			}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 400)
		payload = response.json()
		self.assertEqual(payload['status'], 'error')
		self.assertIn('重复内容', payload['message'])

		group.refresh_from_db()
		self.assertEqual(group.prompt_text, '旧提示词1')


class PromptMediationTests(TestCase):
	def test_mediation_flattens_structured_prompt_and_rewrites_sensitive_phrases(self):
		result = mediate_gpt_image_prompt(
			'皮肤：玻璃肌\n动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n氛围：轻微暧昧氛围\n嘴唇：湿润嘴唇'
		)

		self.assertTrue(result['changed'])
		self.assertIn('玻璃肌', result['optimized_prompt'])
		self.assertIn('finger gently posed near lips, relaxed and natural', result['optimized_prompt'])
		self.assertIn('subtle cinematic mood', result['optimized_prompt'])
		self.assertIn('soft glossy lips', result['optimized_prompt'])
		self.assertNotIn('几乎接触', result['optimized_prompt'])
		self.assertNotIn('暧昧', result['optimized_prompt'])
		self.assertTrue(result['rewrite_details'])
		self.assertTrue(result['structured_outline'])
		self.assertEqual(result['structured_outline'][0]['label'], '外观')
		self.assertIn('弱化动作边界', [item['reason_tag'] for item in result['rewrite_details']])
		self.assertIn('将强动作边界改写为更自然的视觉描述', [item['reason'] for item in result['rewrite_details']])

	def test_mediation_off_keeps_original_prompt(self):
		prompt = '动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n氛围：轻微暧昧氛围'
		result = mediate_gpt_image_prompt(prompt, optimization_level='off')

		self.assertEqual(result['optimization_level'], 'off')
		self.assertEqual(result['optimized_prompt'], prompt)
		self.assertFalse(result['changed'])
		self.assertEqual(result['rewrite_details'], [])

	def test_mediation_legacy_conservative_alias_maps_to_faithful_mode(self):
		result = mediate_gpt_image_prompt('黑色cutout连体衣，紧身', optimization_level='conservative')

		self.assertEqual(result['optimization_level'], 'balanced')
		self.assertNotIn('sleek black halter outfit', result['optimized_prompt'])
		self.assertNotIn('fitted', result['optimized_prompt'])

	def test_mediation_preserves_non_risky_scoped_reference_constraints(self):
		prompt = '人物：参考第1张图\n服装：参考第2张图\n动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）'
		result = mediate_gpt_image_prompt(prompt, optimization_level='balanced')

		self.assertIn('参考第1张图', result['optimized_prompt'])
		self.assertIn('参考第2张图', result['optimized_prompt'])
		self.assertIn('finger gently posed near lips, relaxed and natural', result['optimized_prompt'])

	def test_faithful_mode_applies_lighter_local_rewrites(self):
		prompt = (
			'动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n'
			'氛围：轻微暧昧氛围\n'
			'嘴唇：湿润嘴唇\n'
			'服装：裸露感'
		)
		result = mediate_gpt_image_prompt(prompt, optimization_level='balanced')

		self.assertEqual(result['optimization_level'], 'balanced')
		self.assertIn('finger gently posed near lips, relaxed and natural', result['optimized_prompt'])
		self.assertIn('subtle cinematic mood', result['optimized_prompt'])
		self.assertIn('soft glossy lips', result['optimized_prompt'])
		self.assertIn('minimalist styling', result['optimized_prompt'])
		self.assertNotIn('暧昧', result['optimized_prompt'])

	def test_enhanced_mode_expands_stronger_local_rewrites(self):
		prompt = (
			'动作：指尖轻触下唇\n'
			'神态：迷离眼神，轻咬下唇\n'
			'氛围：欲望感\n'
			'服装：深V，透视薄纱，紧身\n'
			'肤质：汗湿肌肤'
		)
		result = mediate_gpt_image_prompt(prompt, optimization_level='enhanced')

		self.assertEqual(result['optimization_level'], 'enhanced')
		self.assertIn('relaxed hand gesture near face', result['optimized_prompt'])
		self.assertIn('calm confident gaze', result['optimized_prompt'])
		self.assertIn('soft natural lip expression', result['optimized_prompt'])
		self.assertIn('stylized cinematic tension', result['optimized_prompt'])
		self.assertIn('tailored elegant styling', result['optimized_prompt'])
		self.assertIn('fitted', result['optimized_prompt'])
		self.assertIn('dewy skin texture', result['optimized_prompt'])

	def test_balanced_and_enhanced_now_produce_distinct_outputs_for_same_prompt(self):
		prompt = (
			'动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n'
			'氛围：轻微暧昧氛围\n'
			'嘴唇：湿润嘴唇\n'
			'服装：裸露感'
		)
		balanced = mediate_gpt_image_prompt(prompt, optimization_level='balanced')
		enhanced = mediate_gpt_image_prompt(prompt, optimization_level='enhanced')

		self.assertNotEqual(balanced['optimized_prompt'], enhanced['optimized_prompt'])
		self.assertIn('finger gently posed near lips, relaxed and natural', balanced['optimized_prompt'])
		self.assertIn('subtle cinematic mood', balanced['optimized_prompt'])
		self.assertIn('soft glossy lips', balanced['optimized_prompt'])
		self.assertIn('minimalist styling', balanced['optimized_prompt'])
		self.assertIn('relaxed hand gesture near face, clean editorial pose', enhanced['optimized_prompt'])
		self.assertIn('stylized editorial atmosphere', enhanced['optimized_prompt'])
		self.assertIn('natural lip detail', enhanced['optimized_prompt'])
		self.assertIn('refined editorial styling', enhanced['optimized_prompt'])

	def test_visual_rewrite_alias_maps_to_simple_rule_mode(self):
		prompt = '人物：参考第1张图\n服装：参考第2张图\n动作：指尖轻触下唇\n神态：迷离眼神\n氛围：轻微暧昧氛围'
		result = mediate_gpt_image_prompt(prompt, optimization_level='visual_rewrite')

		self.assertEqual(result['optimization_level'], 'enhanced')
		self.assertIn('参考第1张图', result['optimized_prompt'])
		self.assertIn('参考第2张图', result['optimized_prompt'])
		self.assertIn('relaxed hand gesture near face', result['optimized_prompt'])
		self.assertIn('calm confident gaze', result['optimized_prompt'])
		self.assertIn('stylized editorial atmosphere', result['optimized_prompt'])

	def test_mediation_preserves_ratio_and_negative_constraints_with_labels(self):
		prompt = (
			'比例：9:16\n'
			'负面约束：不要改发型，不要改服装，不要改构图比例\n'
			'动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）'
		)
		result = mediate_gpt_image_prompt(prompt, optimization_level='balanced')

		self.assertIn('比例：9:16', result['optimized_prompt'])
		self.assertIn('负面约束：不要改发型, 不要改服装, 不要改构图比例', result['optimized_prompt'])
		self.assertIn('finger gently posed near lips, relaxed and natural', result['optimized_prompt'])
		self.assertIn('比例', [item['label'] for item in result['structured_outline']])
		self.assertIn('约束', [item['label'] for item in result['structured_outline']])

	def test_mediation_does_not_rewrite_locked_negative_constraints(self):
		prompt = '负面约束：不要出现湿润嘴唇，不要暧昧氛围'
		result = mediate_gpt_image_prompt(prompt, optimization_level='enhanced')

		self.assertEqual(result['optimized_prompt'], '负面约束：不要出现湿润嘴唇, 不要暧昧氛围')
		self.assertEqual(result['rewrite_details'], [])

	def test_create_view_supports_numbered_prompt_selection(self):
		group = PromptGroup.objects.create(
			title='多提示词模板',
			prompt_text='提示词1',
			prompts=[
				{'text': '提示词1'},
				{'text': '提示词2'},
				{'text': '提示词3'},
			],
		)

		response = self.client.get(reverse('create'), {
			'template_id': group.pk,
			'prompt_type': '2',
		})

		self.assertEqual(response.status_code, 200)
		initial_data = json.loads(response.context['initial_data_json'])
		self.assertEqual(initial_data['prompt'], '提示词2')
		self.assertEqual([item['text'] for item in initial_data['prompts']], ['提示词1', '提示词2', '提示词3'])

	def test_create_view_registers_gpt_image_2_model_label(self):
		AIModel.objects.filter(name='GPT Image 2').delete()
		Tag.objects.filter(name='GPT Image 2').delete()

		response = self.client.get(reverse('create'))

		self.assertEqual(response.status_code, 200)
		self.assertTrue(AIModel.objects.filter(name='GPT Image 2').exists())
		self.assertTrue(Tag.objects.filter(name='GPT Image 2').exists())

	def test_create_view_registers_gpt_image_2_official_model_label(self):
		AIModel.objects.filter(name='GPT Image 2').delete()
		Tag.objects.filter(name='GPT Image 2').delete()

		response = self.client.get(reverse('create'))

		self.assertEqual(response.status_code, 200)
		self.assertTrue(AIModel.objects.filter(name='GPT Image 2').exists())
		self.assertTrue(Tag.objects.filter(name='GPT Image 2').exists())

	def test_create_view_exposes_official_seedream_models_in_t2i_category(self):
		response = self.client.get(reverse('create'))

		self.assertEqual(response.status_code, 200)
		ai_config = json.loads(response.context['ai_config_json'])
		self.assertEqual(
			ai_config['models']['seedream-4.5-official']['visible_in_categories'],
			['multi', 't2i']
		)
		self.assertEqual(
			ai_config['models']['seedream-5.0-lite-official']['visible_in_categories'],
			['multi', 't2i']
		)

	def test_create_view_exposes_fal_seedream_text_to_image_models_in_t2i_category(self):
		response = self.client.get(reverse('create'))

		self.assertEqual(response.status_code, 200)
		ai_config = json.loads(response.context['ai_config_json'])
		self.assertEqual(
			ai_config['models']['seedream-5.0-lite-fal']['category'],
			't2i'
		)
		self.assertEqual(
			ai_config['models']['seedream-5.0-lite-fal']['endpoint'],
			'fal-ai/bytedance/seedream/v5/lite/text-to-image'
		)
		self.assertEqual(
			ai_config['models']['seedream-4.5-fal']['category'],
			't2i'
		)
		self.assertEqual(
			ai_config['models']['seedream-4.5-fal']['endpoint'],
			'fal-ai/bytedance/seedream/v4.5/text-to-image'
		)
		self.assertEqual(
			ai_config['models']['seedream-4.0-fal']['category'],
			't2i'
		)
		self.assertEqual(
			ai_config['models']['seedream-4.0-fal']['endpoint'],
			'fal-ai/bytedance/seedream/v4/text-to-image'
		)
		self.assertNotEqual(
			ai_config['models']['seedream-5.0-lite-fal']['title'],
			ai_config['models']['seedream-5.0-lite-edit-fal']['title']
		)
		self.assertNotEqual(
			ai_config['models']['seedream-4.5-fal']['title'],
			ai_config['models']['seedream-4.5-edit-fal']['title']
		)

	def test_create_view_maps_saved_gpt_image_2_model_back_to_fal_title(self):
		group = PromptGroup.objects.create(
			title='GPT 编辑作品',
			prompt_text='edit this scene',
			prompts=[{'text': 'edit this scene'}],
			model_info='GPT Image 2',
			provider='fal_ai',
		)

		response = self.client.get(reverse('create'), {
			'template_id': group.pk,
			'prompt_type': '1',
		})

		self.assertEqual(response.status_code, 200)
		initial_data = json.loads(response.context['initial_data_json'])
		self.assertEqual(initial_data['model_info'], 'GPT Image 2 (Fal)')

	def test_create_view_maps_saved_gpt_image_2_model_back_to_official_title(self):
		group = PromptGroup.objects.create(
			title='GPT 官方编辑作品',
			prompt_text='edit this scene with official api',
			prompts=[{'text': 'edit this scene with official api'}],
			model_info='GPT Image 2',
			provider='openai',
		)

		response = self.client.get(reverse('create'), {
			'template_id': group.pk,
			'prompt_type': '1',
		})

		self.assertEqual(response.status_code, 200)
		initial_data = json.loads(response.context['initial_data_json'])
		self.assertEqual(initial_data['model_info'], 'GPT Image 2 (官方)')

	def test_upload_view_includes_gpt_image_2_model_choice(self):
		AIModel.objects.filter(name='GPT Image 2').delete()

		response = self.client.get(reverse('upload'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'GPT Image 2')
		self.assertNotContains(response, 'GPT Image 2 官方')

	def test_create_view_contains_mask_editor_modal(self):
		response = self.client.get(reverse('create'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'maskEditorModal')
		self.assertContains(response, 'create-gpt-conversation-panel')
		self.assertContains(response, 'create-gpt-conversation-send')
		self.assertContains(response, 'create-gpt-conversation-recent')
		self.assertContains(response, 'create-gpt-conversation-quality')
		self.assertContains(response, 'create-gpt-conversation-resolution')
		self.assertContains(response, 'create-gpt-conversation-aspect-ratio')
		self.assertContains(response, 'create-gpt-conversation-optimization-level')
		self.assertContains(response, '增强')
		self.assertNotContains(response, '视觉重写')
		self.assertContains(response, 'create-gpt-prompt-mediation-panel')
		self.assertContains(response, 'create-gpt-conversation-mediation-panel')
		self.assertContains(response, 'create-gpt-prompt-mediation-details')
		self.assertContains(response, 'create-gpt-conversation-mediation-outline')
		self.assertContains(response, '编辑蒙版')
		self.assertNotContains(response, '🔵 图生图')
		self.assertNotContains(response, 'flux-dev')
		self.assertNotContains(response, 'Flux i2i')

	def test_create_view_excludes_model_tags_from_publish_tag_data(self):
		model = AIModel.objects.create(name='测试模型标签')
		plain_tag = Tag.objects.create(name='普通标签')
		model_tag = Tag.objects.create(name=model.name)
		group = PromptGroup.objects.create(
			title='标签过滤',
			prompt_text='prompt',
			prompts=[{'text': 'prompt'}],
			model_info=model.name,
		)
		group.tags.add(plain_tag, model_tag)

		response = self.client.get(reverse('create'), {
			'template_id': group.pk,
			'prompt_type': '1',
		})

		self.assertEqual(response.status_code, 200)
		initial_data = json.loads(response.context['initial_data_json'])
		all_tags = json.loads(response.context['all_tags_json'])
		self.assertEqual(initial_data['tags'], ['普通标签'])
		self.assertIn('普通标签', all_tags)
		self.assertNotIn('测试模型标签', all_tags)

	def test_home_view_exposes_gpt_image_2_in_model_filters(self):
		AIModel.objects.filter(name='GPT Image 2').delete()

		response = self.client.get(reverse('home'))

		self.assertEqual(response.status_code, 200)
		self.assertIn('GPT Image 2', response.context['filter_data']['models'])

	def test_home_view_filter_models_omit_deprecated_gpt_image_2_alias(self):
		AIModel.objects.get_or_create(name='GPT Image 2 官方')

		response = self.client.get(reverse('home'))

		self.assertEqual(response.status_code, 200)
		self.assertNotIn('GPT Image 2 官方', response.context['filter_data']['models'])
		self.assertFalse(AIModel.objects.filter(name='GPT Image 2 官方').exists())
		self.assertFalse(Tag.objects.filter(name='GPT Image 2 官方').exists())

	def test_home_model_filter_orders_latest_groups_first(self):
		older_group = PromptGroup.objects.create(
			title='较早的 GPT Image 2 作品',
			prompt_text='older prompt',
			prompts=[{'text': 'older prompt'}],
			model_info='GPT Image 2',
		)
		newer_group = PromptGroup.objects.create(
			title='较新的 GPT Image 2 作品',
			prompt_text='newer prompt',
			prompts=[{'text': 'newer prompt'}],
			model_info='GPT Image 2',
		)

		now = timezone.now()
		PromptGroup.objects.filter(pk=older_group.pk).update(created_at=now - timedelta(days=2))
		PromptGroup.objects.filter(pk=newer_group.pk).update(created_at=now - timedelta(days=1))

		response = self.client.get(reverse('home'), {'f_model': ['GPT Image 2']})

		self.assertEqual(response.status_code, 200)
		page_ids = [group.pk for group in response.context['page_obj']]
		self.assertLess(page_ids.index(newer_group.pk), page_ids.index(older_group.pk))

	def test_home_model_bar_uses_exact_model_filter_links(self):
		PromptGroup.objects.create(
			title='模型条链接测试',
			prompt_text='prompt',
			prompts=[{'text': 'prompt'}],
			model_info='GPT Image 2',
		)

		response = self.client.get(reverse('home'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '/?f_model=GPT%20Image%202')
		self.assertContains(response, 'data-home-model-filter-link="true"')
		self.assertContains(response, 'id="home-results-region"')
		self.assertContains(response, 'id="home-pagination-region"')

	def test_detail_view_model_datalist_contains_gpt_image_2(self):
		group = PromptGroup.objects.create(
			title='详情页模型联想',
			prompt_text='detail prompt',
			prompts=[{'text': 'detail prompt'}],
			model_info='GPT Image 2',
		)

		response = self.client.get(reverse('detail', args=[group.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '<option value="GPT Image 2"></option>', html=True)

	def test_detail_view_model_datalist_omits_deprecated_gpt_image_2_alias(self):
		AIModel.objects.get_or_create(name='GPT Image 2 官方')
		group = PromptGroup.objects.create(
			title='详情页旧模型别名过滤',
			prompt_text='detail prompt',
			prompts=[{'text': 'detail prompt'}],
			model_info='GPT Image 2',
		)

		response = self.client.get(reverse('detail', args=[group.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertNotContains(response, '<option value="GPT Image 2 官方"></option>', html=True)

	def test_detail_view_provider_datalist_contains_openai_chatgpt_and_volcengine(self):
		group = PromptGroup.objects.create(
			title='详情页渠道联想',
			prompt_text='detail prompt',
			prompts=[{'text': 'detail prompt'}],
			provider='openai',
		)

		response = self.client.get(reverse('detail', args=[group.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '<option value="openai">OpenAI</option>', html=True)
		self.assertContains(response, '<option value="chatgpt">ChatGPT</option>', html=True)
		self.assertContains(response, '<option value="volcengine">火山引擎</option>', html=True)
		self.assertContains(response, 'detail-gpt-conversation-panel')
		self.assertContains(response, 'detail-gpt-conversation-send')
		self.assertContains(response, 'detail-gpt-conversation-recent')
		self.assertContains(response, 'detail-gpt-conversation-quality')
		self.assertContains(response, 'detail-gpt-conversation-resolution')
		self.assertContains(response, 'detail-gpt-conversation-aspect-ratio')
		self.assertContains(response, 'detail-gpt-conversation-optimization-level')
		self.assertContains(response, '增强')
		self.assertNotContains(response, '视觉重写')
		self.assertContains(response, 'detail-gpt-conversation-mediation-panel')
		self.assertContains(response, 'detail-gpt-conversation-mediation-details')
		self.assertContains(response, 'detail-gpt-conversation-mediation-outline')


class AIStudioGenerateDirectTests(TestCase):
	@patch('builtins.open', new_callable=mock_open)
	@patch('gallery.views.requests.get')
	@patch('gallery.views.os.makedirs')
	@patch('gallery.views.get_ai_provider')
	def test_openai_gpt_image_2_can_generate_without_reference_image(self, mock_get_provider, mock_makedirs, mock_requests_get, mock_file_open):
		mock_provider = Mock()
		mock_provider.generate.return_value = ['data:image/png;base64,ZmFrZS1pbWFnZQ==']
		mock_get_provider.return_value = mock_provider

		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-openai',
			'prompt': 'generate a surreal city floating above the ocean',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertEqual(len(payload['saved_paths']), 1)
		mock_requests_get.assert_not_called()

		call_args = mock_provider.generate.call_args
		self.assertEqual(call_args.args[0]['endpoint'], 'gpt-image-2')
		self.assertEqual(call_args.args[1]['quality'], 'medium')
		self.assertEqual(call_args.args[1]['size'], '1536x2736')
		self.assertEqual(call_args.args[2], [])

	@patch('builtins.open', new_callable=mock_open)
	@patch('gallery.views.requests.get')
	@patch('gallery.views.os.makedirs')
	@patch('gallery.views.get_ai_provider')
	def test_openai_gpt_image_2_mediates_prompt_before_provider(self, mock_get_provider, mock_makedirs, mock_requests_get, mock_file_open):
		mock_provider = Mock()
		mock_provider.generate.return_value = ['data:image/png;base64,ZmFrZS1pbWFnZQ==']
		mock_get_provider.return_value = mock_provider

		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-openai',
			'prompt': '动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n氛围：轻微暧昧氛围\n嘴唇：湿润嘴唇',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertIn('optimized_prompt', payload)
		self.assertIn('prompt_mediation', payload)
		self.assertTrue(payload['prompt_mediation']['changed'])
		self.assertTrue(payload['prompt_mediation']['rewrite_details'])
		self.assertTrue(payload['prompt_mediation']['structured_outline'])
		self.assertIn('subtle cinematic mood', payload['optimized_prompt'])
		self.assertNotIn('暧昧', payload['optimized_prompt'])

		call_args = mock_provider.generate.call_args
		self.assertEqual(call_args.args[1]['prompt'], payload['optimized_prompt'])
		self.assertIn('soft glossy lips', call_args.args[1]['prompt'])

	@patch('builtins.open', new_callable=mock_open)
	@patch('gallery.views.requests.get')
	@patch('gallery.views.os.makedirs')
	@patch('gallery.views.get_ai_provider')
	def test_openai_gpt_image_2_maps_visual_rewrite_to_simple_rule_mode(self, mock_get_provider, mock_makedirs, mock_requests_get, mock_file_open):
		mock_provider = Mock()
		mock_provider.generate.return_value = ['data:image/png;base64,ZmFrZS1pbWFnZQ==']
		mock_get_provider.return_value = mock_provider

		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-openai',
			'prompt': '人物：参考第1张图\n服装：参考第2张图\n动作：指尖轻触下唇\n神态：迷离眼神\n氛围：轻微暧昧氛围',
			'prompt_optimization_level': 'visual_rewrite',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertEqual(payload['prompt_mediation']['optimization_level'], 'enhanced')
		self.assertIn('参考第1张图', payload['optimized_prompt'])
		self.assertIn('参考第2张图', payload['optimized_prompt'])
		self.assertIn('relaxed hand gesture near face', payload['optimized_prompt'])
		self.assertIn('calm confident gaze', payload['optimized_prompt'])
		self.assertIn('stylized editorial atmosphere', payload['optimized_prompt'])

		call_args = mock_provider.generate.call_args
		self.assertEqual(call_args.args[1]['prompt'], payload['optimized_prompt'])

	@patch('builtins.open', new_callable=mock_open)
	@patch('gallery.views.requests.get')
	@patch('gallery.views.os.makedirs')
	@patch('gallery.views.get_ai_provider')
	def test_openai_gpt_image_2_can_disable_prompt_optimization(self, mock_get_provider, mock_makedirs, mock_requests_get, mock_file_open):
		mock_provider = Mock()
		mock_provider.generate.return_value = ['data:image/png;base64,ZmFrZS1pbWFnZQ==']
		mock_get_provider.return_value = mock_provider

		original_prompt = '动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n氛围：轻微暧昧氛围'
		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-openai',
			'prompt': original_prompt,
			'prompt_optimization_level': 'off',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertEqual(payload['optimized_prompt'], original_prompt)
		self.assertEqual(payload['prompt_mediation']['optimization_level'], 'off')
		self.assertFalse(payload['prompt_mediation']['changed'])

		call_args = mock_provider.generate.call_args
		self.assertEqual(call_args.args[1]['prompt'], original_prompt)

	@patch('builtins.open', new_callable=mock_open)
	@patch('gallery.views.requests.get')
	@patch('gallery.views.os.makedirs')
	@patch('gallery.views.get_ai_provider')
	def test_openai_gpt_image_2_adaptive_mode_tries_original_prompt_first(self, mock_get_provider, mock_makedirs, mock_requests_get, mock_file_open):
		mock_provider = Mock()
		mock_provider.generate.return_value = ['data:image/png;base64,ZmFrZS1pbWFnZQ==']
		mock_get_provider.return_value = mock_provider

		original_prompt = '动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n氛围：轻微暧昧氛围'
		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-openai',
			'prompt': original_prompt,
			'adaptive_prompt_optimization': 'true',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertEqual(payload['optimized_prompt'], original_prompt)
		self.assertEqual(payload['prompt_mediation']['optimization_level'], 'off')
		self.assertFalse(payload['prompt_mediation']['changed'])

		call_args = mock_provider.generate.call_args
		self.assertEqual(call_args.args[1]['prompt'], original_prompt)

	@patch('gallery.views.get_ai_provider')
	def test_openai_gpt_image_2_adaptive_mode_returns_moderation_failure_with_original_prompt(self, mock_get_provider):
		mock_provider = Mock()
		mock_provider.generate.side_effect = RuntimeError('InputSensitiveContentDetected')
		mock_get_provider.return_value = mock_provider

		original_prompt = '动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n氛围：轻微暧昧氛围'
		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-openai',
			'prompt': original_prompt,
			'adaptive_prompt_optimization': 'true',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'moderation_failed')
		self.assertEqual(payload['optimized_prompt'], original_prompt)
		self.assertEqual(payload['prompt_mediation']['optimization_level'], 'off')
		self.assertFalse(payload['prompt_mediation']['changed'])
		self.assertTrue(payload['can_retry_higher'])
		self.assertEqual(payload['next_optimization_level'], 'balanced')
		self.assertEqual(payload['error_code'], 'input_sensitive_content_detected')

	@patch('gallery.views.get_ai_provider')
	def test_openai_gpt_image_2_adaptive_mode_returns_balanced_prompt_when_balanced_retry_still_fails(self, mock_get_provider):
		mock_provider = Mock()
		mock_provider.generate.side_effect = RuntimeError('InputSensitiveContentDetected')
		mock_get_provider.return_value = mock_provider

		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-openai',
			'prompt': '动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n氛围：轻微暧昧氛围\n嘴唇：湿润嘴唇',
			'adaptive_prompt_optimization': 'true',
			'next_optimization_level': 'balanced',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'moderation_failed')
		self.assertEqual(payload['prompt_mediation']['optimization_level'], 'balanced')
		self.assertTrue(payload['prompt_mediation']['changed'])
		self.assertIn('subtle cinematic mood', payload['optimized_prompt'])
		self.assertIn('soft glossy lips', payload['optimized_prompt'])
		self.assertTrue(payload['can_retry_higher'])
		self.assertEqual(payload['next_optimization_level'], 'enhanced')

	@patch('gallery.views.get_ai_provider')
	def test_openai_gpt_image_2_adaptive_mode_recognizes_openai_safety_system_message(self, mock_get_provider):
		mock_provider = Mock()
		mock_provider.generate.side_effect = RuntimeError('Your request was rejected as a result of our safety system. Please revise your prompt and try again.')
		mock_get_provider.return_value = mock_provider

		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-openai',
			'prompt': '动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n氛围：轻微暧昧氛围',
			'adaptive_prompt_optimization': 'true',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'moderation_failed')
		self.assertEqual(payload['prompt_mediation']['optimization_level'], 'off')
		self.assertTrue(payload['can_retry_higher'])
		self.assertEqual(payload['next_optimization_level'], 'balanced')

	def test_gpt_image_2_requires_reference_image(self):
		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-edit-fal',
			'prompt': 'edit this image',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'error')
		self.assertIn('参考图片', payload['message'])

	@patch('builtins.open', new_callable=mock_open)
	@patch('gallery.views.requests.get')
	@patch('gallery.views.os.makedirs')
	@patch('gallery.views.get_ai_provider')
	def test_gpt_image_2_passes_mask_file_to_provider(self, mock_get_provider, mock_makedirs, mock_requests_get, mock_file_open):
		mock_provider = Mock()
		mock_provider.generate.return_value = ['https://example.com/generated.png']
		mock_get_provider.return_value = mock_provider

		mock_requests_get.return_value = Mock(status_code=200, content=b'generated-image')

		base_image = SimpleUploadedFile('base.png', b'base-image', content_type='image/png')
		mask_image = SimpleUploadedFile('mask.png', b'mask-image', content_type='image/png')

		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-edit-fal',
			'prompt': 'replace the background with a rainy cyberpunk alley',
			'base_images': base_image,
			'mask_url': mask_image,
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertEqual(payload['image_urls'], ['https://example.com/generated.png'])

		call_args = mock_provider.generate.call_args
		self.assertEqual(call_args.args[0]['endpoint'], 'openai/gpt-image-2/edit')
		self.assertEqual(call_args.args[1]['quality'], 'medium')
		self.assertEqual(call_args.args[1]['image_size'], {'width': 1536, 'height': 2736})
		self.assertEqual(len(call_args.args[2]), 1)
		self.assertIn('mask_url', call_args.kwargs['extra_files'])

	@patch('builtins.open', new_callable=mock_open)
	@patch('gallery.views.requests.get')
	@patch('gallery.views.os.makedirs')
	@patch('gallery.views.get_ai_provider')
	def test_gpt_image_2_builds_custom_image_size_from_ratio_and_resolution(self, mock_get_provider, mock_makedirs, mock_requests_get, mock_file_open):
		mock_provider = Mock()
		mock_provider.generate.return_value = ['https://example.com/generated.png']
		mock_get_provider.return_value = mock_provider
		mock_requests_get.return_value = Mock(status_code=200, content=b'generated-image')

		base_image = SimpleUploadedFile('base.png', b'base-image', content_type='image/png')

		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-edit-fal',
			'prompt': 'render this scene at higher resolution',
			'base_images': base_image,
			'image_size_mode': 'custom',
			'aspect_ratio': '16:9',
			'resolution': '4K',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')

		call_args = mock_provider.generate.call_args
		self.assertEqual(call_args.args[1]['image_size'], {'width': 3840, 'height': 2160})
		self.assertNotIn('image_size_mode', call_args.args[1])
		self.assertNotIn('aspect_ratio', call_args.args[1])
		self.assertNotIn('resolution', call_args.args[1])

	@patch('builtins.open', new_callable=mock_open)
	@patch('gallery.views.requests.get')
	@patch('gallery.views.os.makedirs')
	@patch('gallery.views.get_ai_provider')
	def test_openai_gpt_image_2_passes_mask_file_to_provider(self, mock_get_provider, mock_makedirs, mock_requests_get, mock_file_open):
		mock_provider = Mock()
		mock_provider.generate.return_value = ['data:image/png;base64,ZmFrZS1pbWFnZQ==']
		mock_get_provider.return_value = mock_provider

		base_image = SimpleUploadedFile('base.png', b'base-image', content_type='image/png')
		mask_image = SimpleUploadedFile('mask.png', b'mask-image', content_type='image/png')

		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-openai',
			'prompt': 'replace the product box art with a retro neon illustration',
			'base_images': base_image,
			'mask_url': mask_image,
			'resolution': '4K',
			'aspect_ratio': '16:9',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		mock_requests_get.assert_not_called()

		call_args = mock_provider.generate.call_args
		self.assertEqual(call_args.args[0]['endpoint'], 'gpt-image-2')
		self.assertEqual(call_args.args[1]['size'], '3840x2160')
		self.assertEqual(len(call_args.args[2]), 1)
		self.assertIn('mask_url', call_args.kwargs['extra_files'])

	def test_openai_gpt_image_2_rejects_mask_without_reference_image(self):
		mask_image = SimpleUploadedFile('mask.png', b'mask-image', content_type='image/png')

		response = self.client.post(reverse('api_generate_direct'), {
			'model_choice': 'gpt-image-2-openai',
			'prompt': 'only edit the masked region',
			'mask_url': mask_image,
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'error')
		self.assertIn('蒙版', payload['message'])


class GPTImageConversationApiTests(TestCase):
	def setUp(self):
		super().setUp()
		self.media_dir = tempfile.TemporaryDirectory()
		self.override = override_settings(MEDIA_ROOT=self.media_dir.name)
		self.override.enable()

	def tearDown(self):
		self.override.disable()
		self.media_dir.cleanup()
		super().tearDown()

	def _create_group_with_image(self):
		group = PromptGroup.objects.create(
			title='会话源作品',
			prompt_text='base prompt',
			prompts=[{'text': 'base prompt'}],
			model_info='GPT Image 2',
			provider='openai',
		)
		image = ImageItem.objects.create(
			group=group,
			image=SimpleUploadedFile('base.png', b'base-image-bytes', content_type='image/png'),
		)
		return group, image

	def test_create_gpt_image_conversation_records_source_context(self):
		group, image = self._create_group_with_image()

		response = self.client.post(reverse('api_create_gpt_image_conversation'), {
			'source_page': 'detail',
			'model_choice': 'gpt-image-2-openai',
			'source_prompt_group_id': group.pk,
			'source_image_id': image.pk,
			'active_image_id': image.pk,
			'prompt': 'make it more cinematic',
			'latest_params': json.dumps({'quality': 'high'}),
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		conversation = GPTImageConversation.objects.get(conversation_id=payload['conversation']['conversation_id'])
		self.assertEqual(conversation.source_page, 'detail')
		self.assertEqual(conversation.source_prompt_group_id, group.pk)
		self.assertEqual(conversation.source_image_id, image.pk)
		self.assertEqual(conversation.active_image_id, image.pk)
		self.assertEqual(conversation.model_key, 'gpt-image-2-openai')
		self.assertEqual(conversation.model_label, 'GPT Image 2')
		self.assertEqual(conversation.provider, 'openai')
		self.assertEqual(conversation.latest_params, {'quality': 'high'})

	@patch('gallery.views._save_generated_images')
	@patch('gallery.views.get_ai_provider')
	def test_append_turn_uses_active_image_and_updates_active_path(self, mock_get_provider, mock_save_generated_images):
		group, image = self._create_group_with_image()
		conversation = GPTImageConversation.objects.create(
			source_page='detail',
			source_prompt_group=group,
			source_image=image,
			active_image=image,
			active_image_path=image.image.path,
			model_key='gpt-image-2-openai',
			model_label='GPT Image 2',
			provider='openai',
		)

		mock_provider = Mock()
		mock_provider.generate.return_value = ['data:image/png;base64,ZmFrZS1pbWFnZQ==']
		mock_get_provider.return_value = mock_provider
		mock_save_generated_images.return_value = (
			['data:image/png;base64,ZmFrZS1pbWFnZQ=='],
			['C:/generated/round-1.png', 'C:/generated/round-1-alt.png'],
		)

		response = self.client.post(
			reverse('api_append_gpt_image_conversation_turn', kwargs={'conversation_id': conversation.conversation_id}),
			{
				'instruction': 'give the scene a brighter sunset rim light',
				'resolution': '4K',
				'aspect_ratio': '16:9',
			},
		)

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		conversation.refresh_from_db()
		self.assertEqual(conversation.active_image_path, 'C:/generated/round-1.png')
		self.assertEqual(conversation.last_instruction, 'give the scene a brighter sunset rim light')
		self.assertEqual(conversation.latest_params['size'], '3840x2160')
		turn = GPTImageConversationTurn.objects.get(conversation=conversation)
		self.assertEqual(turn.turn_index, 1)
		self.assertEqual(turn.input_image_id, image.pk)
		self.assertEqual(turn.output_image_path, 'C:/generated/round-1.png')
		self.assertEqual(turn.response_payload['saved_paths'][1], 'C:/generated/round-1-alt.png')

		call_args = mock_provider.generate.call_args
		self.assertEqual(call_args.args[0]['endpoint'], 'gpt-image-2')
		self.assertEqual(call_args.args[1]['size'], '3840x2160')
		self.assertEqual(len(call_args.args[2]), 1)

	@patch('gallery.views._save_generated_images')
	@patch('gallery.views.get_ai_provider')
	def test_append_turn_returns_optimized_prompt_for_gpt_image_2(self, mock_get_provider, mock_save_generated_images):
		group, image = self._create_group_with_image()
		conversation = GPTImageConversation.objects.create(
			source_page='detail',
			source_prompt_group=group,
			source_image=image,
			active_image=image,
			active_image_path=image.image.path,
			model_key='gpt-image-2-openai',
			model_label='GPT Image 2',
			provider='openai',
		)

		mock_provider = Mock()
		mock_provider.generate.return_value = ['data:image/png;base64,ZmFrZS1pbWFnZQ==']
		mock_get_provider.return_value = mock_provider
		mock_save_generated_images.return_value = (
			['data:image/png;base64,ZmFrZS1pbWFnZQ=='],
			['C:/generated/round-2.png'],
		)

		response = self.client.post(
			reverse('api_append_gpt_image_conversation_turn', kwargs={'conversation_id': conversation.conversation_id}),
			{
				'instruction': '动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n氛围：轻微暧昧氛围',
			},
		)

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertIn('optimized_prompt', payload)
		self.assertIn('prompt_mediation', payload)
		self.assertTrue(payload['prompt_mediation']['changed'])
		self.assertTrue(payload['prompt_mediation']['rewrite_details'])
		self.assertTrue(payload['prompt_mediation']['structured_outline'])
		self.assertIn('subtle cinematic mood', payload['optimized_prompt'])

		call_args = mock_provider.generate.call_args
		self.assertEqual(call_args.args[1]['prompt'], payload['optimized_prompt'])
		self.assertIn('finger gently posed near lips', call_args.args[1]['prompt'])
		self.assertIn('prompt_mediation', payload)

	@patch('gallery.views._save_generated_images')
	@patch('gallery.views.get_ai_provider')
	def test_append_turn_can_disable_prompt_optimization_for_gpt_image_2(self, mock_get_provider, mock_save_generated_images):
		group, image = self._create_group_with_image()
		conversation = GPTImageConversation.objects.create(
			source_page='detail',
			source_prompt_group=group,
			source_image=image,
			active_image=image,
			active_image_path=image.image.path,
			model_key='gpt-image-2-openai',
			model_label='GPT Image 2',
			provider='openai',
		)

		mock_provider = Mock()
		mock_provider.generate.return_value = ['data:image/png;base64,ZmFrZS1pbWFnZQ==']
		mock_get_provider.return_value = mock_provider
		mock_save_generated_images.return_value = (
			['data:image/png;base64,ZmFrZS1pbWFnZQ=='],
			['C:/generated/round-off.png'],
		)

		original_instruction = '动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n氛围：轻微暧昧氛围'
		response = self.client.post(
			reverse('api_append_gpt_image_conversation_turn', kwargs={'conversation_id': conversation.conversation_id}),
			{
				'instruction': original_instruction,
				'prompt_optimization_level': 'off',
			},
		)

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertEqual(payload['optimized_prompt'], original_instruction)
		self.assertEqual(payload['prompt_mediation']['optimization_level'], 'off')
		self.assertFalse(payload['prompt_mediation']['changed'])

		call_args = mock_provider.generate.call_args
		self.assertEqual(call_args.args[1]['prompt'], original_instruction)

	@patch('gallery.views.get_ai_provider')
	def test_append_turn_returns_moderation_failure_payload_for_adaptive_retry(self, mock_get_provider):
		group, image = self._create_group_with_image()
		conversation = GPTImageConversation.objects.create(
			source_page='detail',
			source_prompt_group=group,
			source_image=image,
			active_image=image,
			active_image_path=image.image.path,
			model_key='gpt-image-2-openai',
			model_label='GPT Image 2',
			provider='openai',
		)

		mock_provider = Mock()
		mock_provider.generate.side_effect = RuntimeError('InputSensitiveContentDetected')
		mock_get_provider.return_value = mock_provider

		original_instruction = '动作：手指停留在下唇前方极近的位置（几乎接触但不触碰）\n氛围：轻微暧昧氛围'
		response = self.client.post(
			reverse('api_append_gpt_image_conversation_turn', kwargs={'conversation_id': conversation.conversation_id}),
			{
				'instruction': original_instruction,
				'adaptive_prompt_optimization': 'true',
			},
		)

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'moderation_failed')
		self.assertEqual(payload['optimized_prompt'], original_instruction)
		self.assertEqual(payload['prompt_mediation']['optimization_level'], 'off')
		self.assertTrue(payload['can_retry_higher'])
		self.assertEqual(payload['next_optimization_level'], 'balanced')
		self.assertEqual(conversation.turns.count(), 0)

	def test_get_and_switch_active_result_use_turn_history(self):
		group, image = self._create_group_with_image()
		conversation = GPTImageConversation.objects.create(
			source_page='detail',
			source_prompt_group=group,
			source_image=image,
			active_image=image,
			active_image_path='C:/generated/current.png',
			model_key='gpt-image-2-openai',
			model_label='GPT Image 2',
			provider='openai',
		)
		turn = GPTImageConversationTurn.objects.create(
			conversation=conversation,
			turn_index=1,
			instruction='first edit',
			input_image=image,
			input_image_path=image.image.path,
			output_image_path='C:/generated/history-choice.png',
			response_payload={'saved_paths': ['C:/generated/history-choice.png']},
		)

		response = self.client.get(reverse('api_get_gpt_image_conversation', kwargs={'conversation_id': conversation.conversation_id}))
		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertEqual(len(payload['conversation']['turns']), 1)

		switch_response = self.client.post(
			reverse('api_set_gpt_image_conversation_active_result', kwargs={'conversation_id': conversation.conversation_id}),
			{
				'turn_id': turn.pk,
				'image_path': 'C:/generated/history-choice.png',
			},
		)

		self.assertEqual(switch_response.status_code, 200)
		conversation.refresh_from_db()
		self.assertEqual(conversation.active_image_path, 'C:/generated/history-choice.png')

	def test_list_recent_gpt_image_conversations_can_filter_by_source_page_and_group(self):
		group_a = PromptGroup.objects.create(title='A', prompt_text='prompt a', prompts=[{'text': 'prompt a'}])
		group_b = PromptGroup.objects.create(title='B', prompt_text='prompt b', prompts=[{'text': 'prompt b'}])
		conversation_a = GPTImageConversation.objects.create(
			source_page='detail',
			source_prompt_group=group_a,
			model_key='gpt-image-2-openai',
			model_label='GPT Image 2',
			provider='openai',
			initial_prompt='prompt a',
		)
		GPTImageConversationTurn.objects.create(
			conversation=conversation_a,
			turn_index=1,
			instruction='turn a',
			output_image_path='C:/a.png',
		)
		GPTImageConversation.objects.create(
			source_page='create',
			model_key='gpt-image-2-openai',
			model_label='GPT Image 2',
			provider='openai',
			initial_prompt='create prompt',
		)
		GPTImageConversation.objects.create(
			source_page='detail',
			source_prompt_group=group_b,
			model_key='gpt-image-2-openai',
			model_label='GPT Image 2',
			provider='openai',
			initial_prompt='prompt b',
		)

		response = self.client.get(reverse('api_list_gpt_image_conversations'), {
			'source_page': 'detail',
			'source_prompt_group_id': group_a.pk,
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertEqual(len(payload['conversations']), 1)
		self.assertEqual(payload['conversations'][0]['conversation_id'], str(conversation_a.conversation_id))
		self.assertEqual(payload['conversations'][0]['turn_count'], 1)


class AppendToExistingGroupApiTests(TestCase):
	@override_settings(MEDIA_ROOT=tempfile.gettempdir())
	@patch('gallery.services.trigger_background_processing')
	def test_append_to_existing_group_returns_detail_card_payload(self, mock_trigger_background_processing):
		group = PromptGroup.objects.create(
			title='目标作品',
			prompt_text='prompt',
			prompts=[{'text': 'prompt'}],
		)

		with tempfile.TemporaryDirectory() as temp_dir:
			generated_path = os.path.join(temp_dir, 'generated.png')
			with open(generated_path, 'wb') as f:
				f.write(b'fake-generated-image')

			response = self.client.post(reverse('api_append_to_existing_group'), {
				'group_id': group.pk,
				'saved_paths': generated_path,
			})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertEqual(payload['type'], 'gen')
		self.assertEqual(len(payload['new_images_html']), 1)
		self.assertEqual(len(payload['new_images_data']), 1)
		self.assertEqual(payload['group_id'], group.pk)

		created_image = ImageItem.objects.get(group=group)
		self.assertEqual(payload['new_images_data'][0]['id'], created_image.pk)
		self.assertIn('img-card-', payload['new_images_html'][0])
		mock_trigger_background_processing.assert_called_once()


class OpenAIOfficialProviderTests(TestCase):
	def _build_png_upload(self, name, color):
		buffer = BytesIO()
		Image.new('RGBA', (64, 64), color=color).save(buffer, format='PNG')
		return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

	@patch.dict('os.environ', {'OPENAI_API_KEY': 'test-openai-key'})
	@patch('gallery.ai_providers.httpx.Client')
	def test_openai_provider_uses_generations_endpoint_for_text_only(self, mock_httpx_client):
		mock_client = Mock()
		mock_response = Mock()
		mock_response.is_error = False
		mock_response.json.return_value = {
			'data': [{'b64_json': 'ZmFrZS1pbWFnZQ=='}],
			'output_format': 'png',
		}
		mock_client.post.return_value = mock_response
		mock_httpx_client.return_value.__enter__.return_value = mock_client

		provider = get_ai_provider('openai')
		model_config = {'endpoint': 'gpt-image-2'}
		result = provider.generate(model_config, {
			'prompt': 'generate a cinematic astronaut portrait',
			'num_images': 2,
			'quality': 'medium',
			'size': '1536x2736',
			'output_format': 'png',
			'moderation': 'auto',
			'background': 'auto',
		})

		self.assertEqual(result, ['data:image/png;base64,ZmFrZS1pbWFnZQ=='])
		mock_client.post.assert_called_once()
		call_args = mock_client.post.call_args
		self.assertEqual(call_args.args[0], 'https://api.openai.com/v1/images/generations')
		self.assertEqual(call_args.kwargs['json']['model'], 'gpt-image-2')
		self.assertEqual(call_args.kwargs['json']['n'], 2)
		self.assertEqual(call_args.kwargs['json']['size'], '1536x2736')

	@patch.dict('os.environ', {'OPENAI_API_KEY': 'test-openai-key'})
	@patch('gallery.ai_providers.httpx.Client')
	def test_openai_provider_uses_edits_endpoint_for_reference_images(self, mock_httpx_client):
		mock_client = Mock()
		mock_response = Mock()
		mock_response.is_error = False
		mock_response.json.return_value = {
			'data': [{'b64_json': 'ZmFrZS1lZGl0ZWQ='}],
			'output_format': 'png',
		}
		mock_client.post.return_value = mock_response
		mock_httpx_client.return_value.__enter__.return_value = mock_client

		provider = get_ai_provider('openai')
		model_config = {'endpoint': 'gpt-image-2'}
		base_image = self._build_png_upload('base.png', color=(255, 0, 0, 255))
		mask_image = self._build_png_upload('mask.png', color=(0, 0, 0, 255))

		result = provider.generate(
			model_config,
			{
				'prompt': 'replace the center object with a crystal flower',
				'num_images': 1,
				'quality': 'high',
				'size': '3840x2160',
				'output_format': 'png',
			},
			base_image_files=[base_image],
			extra_files={'mask_url': mask_image},
		)

		self.assertEqual(result, ['data:image/png;base64,ZmFrZS1lZGl0ZWQ='])
		mock_client.post.assert_called_once()
		call_args = mock_client.post.call_args
		self.assertEqual(call_args.args[0], 'https://api.openai.com/v1/images/edits')
		self.assertEqual(call_args.kwargs['data']['model'], 'gpt-image-2')
		self.assertEqual(call_args.kwargs['data']['size'], '3840x2160')
		files = call_args.kwargs['files']
		self.assertEqual(files[0][0], 'image[]')
		self.assertEqual(files[1][0], 'mask')


class GalleryNavigationTests(TestCase):
	def test_gallery_home_navbar_contains_visuals_entry(self):
		response = self.client.get(reverse('home'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, reverse('visuals:home'))
		self.assertContains(response, 'Visuals 资源库')

	def test_gallery_home_navbar_contains_google_flow_entry(self):
		response = self.client.get(reverse('home'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'https://labs.google/fx/tools/flow')
		self.assertContains(response, 'Google Flow')


class GroupListApiTests(TestCase):
	def test_append_search_can_expand_all_variants_in_same_series(self):
		main_group = PromptGroup.objects.create(
			title='主版本',
			prompt_text='cinematic portrait with soft rim light',
			is_main_variant=True,
		)
		variant_group = PromptGroup.objects.create(
			title='次版本',
			prompt_text='ultra specific append modal token',
		)
		PromptGroup.objects.filter(pk=variant_group.pk).update(group_id=main_group.group_id)
		variant_group.refresh_from_db()

		response = self.client.get(reverse('group_list_api'), {
			'q': 'ultra specific append modal token',
			'include_variants': '1',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		result_ids = {item['id'] for item in payload['results']}

		self.assertSetEqual(result_ids, {main_group.id, variant_group.id})
		self.assertTrue(all(item['count'] == 2 for item in payload['results']))

	def test_default_group_search_keeps_representative_only(self):
		main_group = PromptGroup.objects.create(
			title='主版本',
			prompt_text='cinematic portrait with soft rim light',
			is_main_variant=True,
		)
		variant_group = PromptGroup.objects.create(
			title='次版本',
			prompt_text='series only hidden token',
		)
		PromptGroup.objects.filter(pk=variant_group.pk).update(group_id=main_group.group_id)

		response = self.client.get(reverse('group_list_api'), {
			'q': 'series only hidden token',
		})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(len(payload['results']), 1)
		self.assertEqual(payload['results'][0]['id'], main_group.id)


class SimilarGroupsApiTests(TestCase):
	def test_similarity_uses_prompt_text_zh(self):
		target_group = PromptGroup.objects.create(
			title='中文命中',
			prompt_text='totally unrelated english prompt',
			prompt_text_zh='银发少女 霓虹雨夜',
		)
		PromptGroup.objects.create(
			title='干扰项',
			prompt_text='warm sunset portrait',
			prompt_text_zh='海边风景',
		)

		response = self.client.post(
			reverse('api_get_similar_groups_by_prompt'),
			data=json.dumps({'prompt': '银发少女 霓虹雨夜'}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertEqual(payload['results'][0]['id'], target_group.id)
		self.assertEqual(payload['results'][0]['prompt_text'], '银发少女 霓虹雨夜')
		self.assertEqual(payload['results'][0]['matched_prompt_field'], 'prompt_2')
		self.assertEqual(payload['results'][0]['matched_prompt_label'], '提示词2')

	def test_similarity_uses_negative_prompt(self):
		target_group = PromptGroup.objects.create(
			title='负向命中',
			prompt_text='hero portrait in studio lighting',
			negative_prompt='lowres, blurry, extra fingers, bad hands',
		)
		PromptGroup.objects.create(
			title='干扰项',
			prompt_text='forest elf cinematic scene',
			negative_prompt='oversaturated, duplicate face',
		)

		response = self.client.post(
			reverse('api_get_similar_groups_by_prompt'),
			data=json.dumps({'prompt': 'lowres blurry extra fingers bad hands'}),
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['status'], 'success')
		self.assertEqual(payload['results'][0]['id'], target_group.id)
		self.assertEqual(payload['results'][0]['prompt_text'], 'lowres, blurry, extra fingers, bad hands')
		self.assertEqual(payload['results'][0]['matched_prompt_field'], 'prompt_2')
		self.assertEqual(payload['results'][0]['matched_prompt_label'], '提示词2')


class DetailImageOrderingTests(TestCase):
	class DummyImage:
		def __init__(self, label, vector=None):
			self.label = label
			self.feature_vector = vector

	def make_vector(self, values):
		return np.array(values, dtype=np.float32).tobytes()

	def test_order_images_by_similarity_clusters_neighbors(self):
		image_a = self.DummyImage('A', self.make_vector([0.98, 0.02, 0.0]))
		image_b = self.DummyImage('B', self.make_vector([0.0, 1.0, 0.0]))
		image_c = self.DummyImage('C', self.make_vector([1.0, 0.0, 0.0]))

		ordered = _order_images_by_similarity([image_c, image_b, image_a])

		self.assertEqual([image.label for image in ordered], ['C', 'A', 'B'])

	def test_order_images_by_similarity_appends_items_without_vectors(self):
		image_a = self.DummyImage('A', self.make_vector([1.0, 0.0, 0.0]))
		image_b = self.DummyImage('B')
		image_c = self.DummyImage('C', self.make_vector([0.99, 0.01, 0.0]))

		ordered = _order_images_by_similarity([image_a, image_b, image_c])

		self.assertEqual([image.label for image in ordered], ['A', 'C', 'B'])


class DetailViewOrganizerTests(TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.temp_media_root = tempfile.mkdtemp()
		cls.override_media_root = override_settings(MEDIA_ROOT=cls.temp_media_root)
		cls.override_media_root.enable()

	@classmethod
	def tearDownClass(cls):
		cls.override_media_root.disable()
		shutil.rmtree(cls.temp_media_root, ignore_errors=True)
		super().tearDownClass()

	def make_uploaded_image(self, name, size=(16, 16), color=(255, 0, 0)):
		buffer = BytesIO()
		Image.new('RGB', size, color).save(buffer, format='PNG')
		return SimpleUploadedFile(name, buffer.getvalue(), content_type='image/png')

	def make_vector(self, values):
		return np.array(values, dtype=np.float32).tobytes()

	def test_detail_defaults_to_similarity_sort_for_images(self):
		group = PromptGroup.objects.create(title='排序详情页', prompt_text='detail sort prompt')
		oldest = ImageItem.objects.create(
			group=group,
			image=self.make_uploaded_image('oldest.png', color=(255, 0, 0)),
			feature_vector=self.make_vector([0.98, 0.02, 0.0]),
		)
		middle = ImageItem.objects.create(
			group=group,
			image=self.make_uploaded_image('middle.png', color=(0, 255, 0)),
			feature_vector=self.make_vector([0.0, 1.0, 0.0]),
		)
		newest = ImageItem.objects.create(
			group=group,
			image=self.make_uploaded_image('newest.png', color=(0, 0, 255)),
			feature_vector=self.make_vector([1.0, 0.0, 0.0]),
		)

		response = self.client.get(reverse('detail', args=[group.pk]))

		self.assertEqual(response.status_code, 200)
		self.assertEqual([item.pk for item in response.context['images_list']], [newest.pk, oldest.pk, middle.pk])
		self.assertEqual(response.context['sort_mode'], 'similar')
		self.assertEqual(response.context['ratio_filter'], 'all')

	def test_detail_preserves_sort_and_ratio_params_in_detail_navigation_links(self):
		group = PromptGroup.objects.create(title='当前详情', prompt_text='current detail prompt')
		sibling = PromptGroup.objects.create(title='同组版本', prompt_text='sibling detail prompt')
		PromptGroup.objects.filter(pk=sibling.pk).update(group_id=group.group_id)
		sibling.refresh_from_db()

		ImageItem.objects.create(
			group=group,
			image=self.make_uploaded_image('current.png', color=(200, 120, 0)),
			feature_vector=self.make_vector([1.0, 0.0, 0.0]),
		)
		ImageItem.objects.create(
			group=sibling,
			image=self.make_uploaded_image('sibling.png', color=(0, 120, 200)),
			feature_vector=self.make_vector([0.0, 1.0, 0.0]),
		)

		response = self.client.get(reverse('detail', args=[group.pk]), {
			'sort': 'latest',
			'ratio': 'portrait',
		})

		self.assertEqual(response.status_code, 200)
		self.assertEqual(response.context['sort_mode'], 'latest')
		self.assertEqual(response.context['ratio_filter'], 'portrait')
		self.assertContains(response, 'sort=latest')
		self.assertContains(response, 'ratio=portrait')
