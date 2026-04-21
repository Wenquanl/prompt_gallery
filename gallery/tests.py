from django.test import TestCase
from django.urls import reverse
import json

from .models import PromptGroup


class GalleryNavigationTests(TestCase):
	def test_gallery_home_navbar_contains_visuals_entry(self):
		response = self.client.get(reverse('home'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, reverse('visuals:home'))
		self.assertContains(response, 'Visuals 资源库')


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
		self.assertEqual(payload['results'][0]['matched_prompt_field'], 'prompt_text_zh')
		self.assertEqual(payload['results'][0]['matched_prompt_label'], '中文提示词')

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
		self.assertEqual(payload['results'][0]['matched_prompt_field'], 'negative_prompt')
		self.assertEqual(payload['results'][0]['matched_prompt_label'], '负向提示词')
