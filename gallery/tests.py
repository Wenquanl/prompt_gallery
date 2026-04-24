from io import BytesIO
import shutil
import tempfile
import json
from unittest.mock import Mock, mock_open, patch

import numpy as np
from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from .ai_providers import get_ai_provider
from .models import AIModel, ImageItem, PromptGroup, Tag
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
