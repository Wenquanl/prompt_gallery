import shutil
import subprocess
import tempfile
import warnings
from datetime import timedelta
from pathlib import Path
from unittest.mock import call, patch

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from gallery.models import Tag

from . import tasks as tasks_module
from . import views as views_module
from .models import Collection, SourceRoot, VisualResource
from .sync import detect_resource_type, sync_source_root
from .tasks import run_index_visual_resource


MINIMAL_GIF = (
	b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04'
	b'\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
)


class VisualsLibraryTests(TestCase):
	def setUp(self):
		self.temp_dir = Path(tempfile.mkdtemp())

	def tearDown(self):
		shutil.rmtree(self.temp_dir, ignore_errors=True)

	def test_homepage_cards_navigate_to_detail(self):
		resource = VisualResource.objects.create(
			title='Card Target',
			file_path=str(self.temp_dir / 'target.jpg'),
			resource_type='image',
			status='completed',
		)

		response = self.client.get(reverse('visuals:home'))

		self.assertContains(response, reverse('visuals:resource_detail', args=[resource.id]))
		self.assertContains(response, f'return_card={resource.id}')
		self.assertContains(response, 'page=1')
		self.assertContains(response, 'id="library-app"')
		self.assertContains(response, '资源源')
		self.assertContains(response, reverse('home'))
		self.assertContains(response, '前往 Gallery')
		self.assertNotContains(response, '保存并立即扫描')

	@patch('visuals.sync._queue_index')
	def test_scan_visuals_creates_resources_and_marks_missing(self, mock_index_task):
		gif_path = self.temp_dir / 'sample.gif'
		gif_path.write_bytes(MINIMAL_GIF)
		model_path = self.temp_dir / 'dream.safetensors'
		model_path.write_text('fake model content', encoding='utf-8')

		call_command('scan_visuals', str(self.temp_dir))

		self.assertEqual(VisualResource.objects.count(), 2)
		self.assertTrue(VisualResource.objects.filter(resource_type='gif', title='sample').exists())
		self.assertTrue(VisualResource.objects.filter(resource_type='model', title='dream').exists())
		self.assertEqual(mock_index_task.call_count, 2)

		model_path.unlink()
		call_command('scan_visuals', str(self.temp_dir))

		missing_resource = VisualResource.objects.get(file_path=str(model_path))
		self.assertTrue(missing_resource.is_missing)

	def test_library_view_filters_by_query_and_type(self):
		source = SourceRoot.objects.create(name='图库', root_path=str(self.temp_dir))
		VisualResource.objects.create(
			title='Sunset',
			file_path=str(self.temp_dir / 'sunset.jpg'),
			relative_path='sunset.jpg',
			source_root=source,
			resource_type='image',
			status='completed',
		)
		VisualResource.objects.create(
			title='Demo Reel',
			file_path=str(self.temp_dir / 'demo.mp4'),
			relative_path='demo.mp4',
			source_root=source,
			resource_type='video',
			status='completed',
		)

		response = self.client.get(reverse('visuals:home'), {'q': 'Sun', 'type': 'image'})

		self.assertContains(response, 'Sunset')
		self.assertNotContains(response, 'Demo Reel')

	def test_library_view_supports_multiple_resource_types(self):
		source = SourceRoot.objects.create(name='图库', root_path=str(self.temp_dir))
		VisualResource.objects.create(
			title='Still Frame',
			file_path=str(self.temp_dir / 'still.jpg'),
			relative_path='still.jpg',
			source_root=source,
			resource_type='image',
			status='completed',
		)
		VisualResource.objects.create(
			title='Clip Reel',
			file_path=str(self.temp_dir / 'clip.mp4'),
			relative_path='clip.mp4',
			source_root=source,
			resource_type='video',
			status='completed',
		)
		VisualResource.objects.create(
			title='Rig File',
			file_path=str(self.temp_dir / 'rig.blend'),
			relative_path='rig.blend',
			source_root=source,
			resource_type='model',
			status='completed',
		)

		response = self.client.get(reverse('visuals:home'), [('type', 'image'), ('type', 'video')])

		self.assertContains(response, 'Still Frame')
		self.assertContains(response, 'Clip Reel')
		self.assertNotContains(response, 'Rig File')
		self.assertContains(response, 'value="image" checked')
		self.assertContains(response, 'value="video" checked')

	def test_library_view_has_tag_quick_filter_and_supports_tag_filtering(self):
		source = SourceRoot.objects.create(name='图库', root_path=str(self.temp_dir))
		landscape = Tag.objects.create(name='风景')
		portrait = Tag.objects.create(name='人像')
		matched = VisualResource.objects.create(
			title='Mountain Shot',
			file_path=str(self.temp_dir / 'mountain.jpg'),
			relative_path='mountain.jpg',
			source_root=source,
			resource_type='image',
			status='completed',
		)
		other = VisualResource.objects.create(
			title='Portrait Shot',
			file_path=str(self.temp_dir / 'portrait.jpg'),
			relative_path='portrait.jpg',
			source_root=source,
			resource_type='image',
			status='completed',
		)
		matched.tags.add(landscape)
		other.tags.add(portrait)

		response = self.client.get(reverse('visuals:home'), {'tag': str(landscape.id)})

		self.assertContains(response, '标签快捷筛选')
		self.assertContains(response, 'id="tag-sel"')
		self.assertContains(response, 'id="collection-sel"')
		self.assertContains(response, 'minmax(170px, 0.72fr) minmax(170px, 0.72fr)')
		self.assertContains(response, 'Mountain Shot')
		self.assertNotContains(response, 'Portrait Shot')
		self.assertContains(response, f'<option value="{landscape.id}" selected>风景</option>', html=True)

	def test_homepage_pagination_shows_numbered_navigation(self):
		for index in range(25):
			VisualResource.objects.create(
				title=f'Resource {index}',
				file_path=str(self.temp_dir / f'resource-{index}.jpg'),
				resource_type='image',
				status='completed',
			)

		response = self.client.get(reverse('visuals:home'))

		self.assertContains(response, 'aria-label="分页导航"')
		self.assertContains(response, '第 1 / 2 页')
		self.assertContains(response, '每页 24 项')
		self.assertContains(response, 'class="page-number is-current"')
		self.assertContains(response, 'page=2')
		self.assertContains(response, 'data-pagination-jump')
		self.assertContains(response, 'aria-label="输入页码跳转"')
		self.assertContains(response, '>跳转</button>')

	def test_detect_resource_type_treats_blender_files_as_model(self):
		self.assertEqual(detect_resource_type(Path('scene.blend')), 'model')
		self.assertEqual(detect_resource_type(Path('scene.blender')), 'model')

	def test_toggle_like_updates_resource(self):
		resource = VisualResource.objects.create(
			title='Clip',
			file_path=str(self.temp_dir / 'clip.mp4'),
			resource_type='video',
			status='completed',
		)

		response = self.client.post(reverse('visuals:toggle_like', args=[resource.id]), {'next': reverse('visuals:home')})

		self.assertEqual(response.status_code, 302)
		resource.refresh_from_db()
		self.assertTrue(resource.is_liked)

	def test_resource_detail_renders_modal_preview_and_explorer_action(self):
		previous_resource = VisualResource.objects.create(
			title='Before',
			file_path=str(self.temp_dir / 'before.jpg'),
			resource_type='image',
			status='completed',
		)
		resource = VisualResource.objects.create(
			title='Cover',
			file_path=str(self.temp_dir / 'cover.jpg'),
			resource_type='image',
			status='completed',
		)
		next_resource = VisualResource.objects.create(
			title='After',
			file_path=str(self.temp_dir / 'after.jpg'),
			resource_type='image',
			status='completed',
		)

		response = self.client.get(reverse('visuals:resource_detail', args=[resource.id]), {'page': 1, 'return_card': resource.id})

		self.assertContains(response, 'id="preview-modal"')
		self.assertContains(response, '打开所在位置')
		self.assertContains(response, reverse('visuals:open_resource_in_explorer', args=[resource.id]))
		self.assertContains(response, f'data-preview-url="{reverse("visuals:preview_resource", args=[resource.id])}"')
		self.assertContains(response, f'href="{reverse("visuals:home")}?page=1#card-{resource.id}"')
		self.assertContains(response, f'href="{reverse("visuals:resource_detail", args=[next_resource.id])}?page=1&amp;return_card={next_resource.id}"')
		self.assertContains(response, f'href="{reverse("visuals:resource_detail", args=[previous_resource.id])}?page=1&amp;return_card={previous_resource.id}"')
		self.assertContains(response, '前一个')
		self.assertContains(response, '后一个')

	@patch('visuals.views.platform.system', return_value='Windows')
	@patch('visuals.views.subprocess.Popen')
	def test_open_resource_in_explorer_selects_current_file(self, mock_popen, mock_platform_system):
		file_path = self.temp_dir / 'selected.png'
		file_path.write_bytes(b'image-data')
		resource = VisualResource.objects.create(
			title='Selected',
			file_path=str(file_path),
			resource_type='image',
			status='completed',
		)

		response = self.client.post(
			reverse('visuals:open_resource_in_explorer', args=[resource.id]),
			{'next': reverse('visuals:resource_detail', args=[resource.id])},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		mock_popen.assert_called_once_with(['explorer', '/select,', str(file_path.resolve())])
		self.assertContains(response, '已在资源管理器中定位到当前文件。')

	@patch('visuals.tasks.index_visual_resource_task')
	def test_batch_action_adds_tag_and_reindexes(self, mock_index_task):
		resource = VisualResource.objects.create(
			title='Forest',
			file_path=str(self.temp_dir / 'forest.png'),
			resource_type='image',
			status='completed',
		)

		response = self.client.post(
			reverse('visuals:batch_action'),
			{
				'action': 'add_tag',
				'resource_ids': [str(resource.id)],
				'tag_name': 'landscape',
				'next': reverse('visuals:home'),
			},
		)

		self.assertEqual(response.status_code, 302)
		resource.refresh_from_db()
		self.assertTrue(resource.tags.filter(name='landscape').exists())

		response = self.client.post(
			reverse('visuals:batch_action'),
			{
				'action': 'reindex',
				'resource_ids': [str(resource.id)],
				'next': reverse('visuals:home'),
			},
		)

		self.assertEqual(response.status_code, 302)
		resource.refresh_from_db()
		self.assertEqual(resource.status, 'pending')
		mock_index_task.assert_called_once_with(resource.id)

	def test_batch_action_can_remove_from_library_only(self):
		file_path = self.temp_dir / 'forest.png'
		file_path.write_bytes(b'fake')
		resource = VisualResource.objects.create(
			title='Forest',
			file_path=str(file_path),
			resource_type='image',
			status='completed',
		)

		response = self.client.post(
			reverse('visuals:batch_action'),
			{
				'action': 'remove_from_library',
				'resource_ids': [str(resource.id)],
				'next': reverse('visuals:home'),
			},
		)

		self.assertEqual(response.status_code, 302)
		self.assertFalse(VisualResource.objects.filter(id=resource.id).exists())
		self.assertTrue(file_path.exists())

	def test_run_source_metadata_action_handles_empty_source(self):
		source_dir = self.temp_dir / 'source-a'
		source_dir.mkdir()
		source = SourceRoot.objects.create(name='资源源A', root_path=str(source_dir))

		result = tasks_module.run_source_metadata_action(source.id, 'add_tag', '角色')

		self.assertFalse(result['applied'])
		source.refresh_from_db()
		self.assertEqual(source.metadata_task_state, 'done')
		self.assertIn('没有可处理资源', source.metadata_task_message)

	def test_run_source_metadata_action_adds_tag_to_all_resources(self):
		source_dir = self.temp_dir / 'source-a'
		other_dir = self.temp_dir / 'source-b'
		source_dir.mkdir()
		other_dir.mkdir()
		source = SourceRoot.objects.create(name='资源源A', root_path=str(source_dir))
		other_source = SourceRoot.objects.create(name='资源源B', root_path=str(other_dir))
		first = VisualResource.objects.create(title='A1', file_path=str(source_dir / 'a1.png'), source_root=source, resource_type='image')
		second = VisualResource.objects.create(title='A2', file_path=str(source_dir / 'a2.png'), source_root=source, resource_type='image')
		other = VisualResource.objects.create(title='B1', file_path=str(other_dir / 'b1.png'), source_root=other_source, resource_type='image')

		result = tasks_module.run_source_metadata_action(source.id, 'add_tag', '角色')

		self.assertTrue(result['applied'])
		self.assertTrue(first.tags.filter(name='角色').exists())
		self.assertTrue(second.tags.filter(name='角色').exists())
		self.assertFalse(other.tags.filter(name='角色').exists())

	@patch('visuals.tasks._sync_visuals_to_meili')
	def test_run_source_metadata_action_batches_metadata_sync(self, mock_sync_visuals):
		source_dir = self.temp_dir / 'source-a'
		source_dir.mkdir()
		source = SourceRoot.objects.create(name='资源源A', root_path=str(source_dir))
		first = VisualResource.objects.create(title='A1', file_path=str(source_dir / 'a1.png'), source_root=source, resource_type='image')
		second = VisualResource.objects.create(title='A2', file_path=str(source_dir / 'a2.png'), source_root=source, resource_type='image')

		result = tasks_module.run_source_metadata_action(source.id, 'add_tag', '批量标签')

		self.assertTrue(result['applied'])
		mock_sync_visuals.assert_called_once()
		synced_ids = list(mock_sync_visuals.call_args.args[0].values_list('id', flat=True))
		self.assertEqual(synced_ids, [first.id, second.id])
		source.refresh_from_db()
		self.assertEqual(source.metadata_task_state, 'done')

	def test_run_source_metadata_action_can_remove_collection_from_all_resources(self):
		source_dir = self.temp_dir / 'source-a'
		other_dir = self.temp_dir / 'source-b'
		source_dir.mkdir()
		other_dir.mkdir()
		source = SourceRoot.objects.create(name='资源源A', root_path=str(source_dir))
		other_source = SourceRoot.objects.create(name='资源源B', root_path=str(other_dir))
		collection = Collection.objects.create(name='主合集')
		first = VisualResource.objects.create(title='A1', file_path=str(source_dir / 'a1.png'), source_root=source, resource_type='image')
		second = VisualResource.objects.create(title='A2', file_path=str(source_dir / 'a2.png'), source_root=source, resource_type='image')
		other = VisualResource.objects.create(title='B1', file_path=str(other_dir / 'b1.png'), source_root=other_source, resource_type='image')
		first.collections.add(collection)
		second.collections.add(collection)
		other.collections.add(collection)

		result = tasks_module.run_source_metadata_action(source.id, 'remove_collection', '主合集')

		self.assertTrue(result['applied'])
		self.assertFalse(first.collections.filter(name='主合集').exists())
		self.assertFalse(second.collections.filter(name='主合集').exists())
		self.assertTrue(other.collections.filter(name='主合集').exists())

	@patch('visuals.views.enqueue_source_metadata_action')
	def test_source_root_resource_action_queues_background_task(self, mock_enqueue_metadata_action):
		source_dir = self.temp_dir / 'queued-source'
		source_dir.mkdir()
		source = SourceRoot.objects.create(name='资源源A', root_path=str(source_dir))
		mock_enqueue_metadata_action.return_value = True

		response = self.client.post(
			reverse('visuals:source_root_resource_action', args=[source.id]),
			{
				'action': 'add_collection',
				'collection_name': '待处理合集',
				'next': reverse('visuals:sources'),
			},
			follow=True,
		)

		self.assertEqual(response.status_code, 200)
		mock_enqueue_metadata_action.assert_called_once_with(source, 'add_collection', '待处理合集')
		self.assertContains(response, '已提交后台任务')

	@patch('visuals.tasks.source_root_metadata_action_task')
	def test_enqueue_source_metadata_action_marks_source_queued(self, mock_metadata_task):
		source_dir = self.temp_dir / 'queued-source'
		source_dir.mkdir()
		source = SourceRoot.objects.create(name='资源源A', root_path=str(source_dir))

		queued = tasks_module.enqueue_source_metadata_action(source, 'add_tag', '角色')

		self.assertTrue(queued)
		mock_metadata_task.assert_called_once_with(source.id, 'add_tag', '角色')
		source.refresh_from_db()
		self.assertEqual(source.metadata_task_state, 'queued')
		self.assertEqual(source.metadata_task_message, '等待后台任务')

	def test_sources_progress_includes_metadata_task_status(self):
		source_dir = self.temp_dir / 'queued-source'
		source_dir.mkdir()
		source = SourceRoot.objects.create(
			name='资源源A',
			root_path=str(source_dir),
			metadata_task_state='running',
			metadata_task_action='add_tag',
			metadata_task_target='角色',
			metadata_task_total=20,
			metadata_task_message='处理中 · 20 项',
		)

		response = self.client.get(reverse('visuals:sources_progress'))

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['sources'][0]['id'], source.id)
		self.assertEqual(payload['sources'][0]['metadata_task_state'], 'running')
		self.assertEqual(payload['sources'][0]['metadata_task_label'], '处理中')
		self.assertEqual(payload['sources'][0]['metadata_task_message'], '处理中 · 20 项')

	def test_duplicates_view_groups_same_hash(self):
		source = SourceRoot.objects.create(name='媒体库', root_path=str(self.temp_dir))
		first_path = self.temp_dir / 'a.jpg'
		second_path = self.temp_dir / 'b.jpg'
		first_path.write_bytes(b'fake-image-a')
		second_path.write_bytes(b'fake-image-b')
		VisualResource.objects.create(
			title='A',
			file_path=str(first_path),
			relative_path='shots/a.jpg',
			source_root=source,
			resource_type='image',
			status='completed',
			file_hash='dup-001',
		)
		second_resource = VisualResource.objects.create(
			title='B',
			file_path=str(second_path),
			relative_path='shots/b.jpg',
			source_root=source,
			resource_type='image',
			status='completed',
			file_hash='dup-001',
		)

		response = self.client.get(reverse('visuals:duplicates'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'dup-001')
		self.assertContains(response, 'A')
		self.assertContains(response, 'B')
		self.assertContains(response, f'{reverse("visuals:preview_resource", args=[second_resource.id])}?variant=card')

	@patch('visuals.models._sync_visual_to_meili')
	def test_duplicates_view_uses_home_style_pagination(self, _mock_meili_sync):
		source = SourceRoot.objects.create(name='重复源', root_path=str(self.temp_dir))
		for index in range(11):
			for suffix in ('a', 'b'):
				file_path = self.temp_dir / f'dupe-{index}-{suffix}.jpg'
				file_path.write_bytes(f'group-{index}-{suffix}'.encode('utf-8'))
				VisualResource.objects.create(
					title=f'Dupe {index} {suffix.upper()}',
					file_path=str(file_path),
					relative_path=f'duplicates/{index}/{suffix}.jpg',
					source_root=source,
					resource_type='image',
					status='completed',
					file_hash=f'dup-{index:03d}',
				)

		first_page = self.client.get(reverse('visuals:duplicates'))

		self.assertEqual(first_page.status_code, 200)
		self.assertContains(first_page, 'aria-label="分页导航"')
		self.assertContains(first_page, '第 1 / 2 页')
		self.assertContains(first_page, '每页 10 组')
		self.assertContains(first_page, 'class="page-number is-current"')
		self.assertContains(first_page, '?page=2')
		self.assertContains(first_page, 'data-pagination-jump')
		self.assertContains(first_page, 'dup-009')
		self.assertNotContains(first_page, 'dup-010')

		second_page = self.client.get(reverse('visuals:duplicates'), {'page': 2})

		self.assertEqual(second_page.status_code, 200)
		self.assertContains(second_page, '第 2 / 2 页')
		self.assertContains(second_page, 'dup-010')
		self.assertNotContains(second_page, 'dup-000')

	def test_sidebar_source_folder_filter(self):
		source = SourceRoot.objects.create(name='归档盘', root_path=str(self.temp_dir))
		VisualResource.objects.create(
			title='Mountain',
			file_path=str(self.temp_dir / 'mountain.jpg'),
			relative_path='travel/mountain.jpg',
			source_root=source,
			resource_type='image',
			status='completed',
		)
		VisualResource.objects.create(
			title='Portrait',
			file_path=str(self.temp_dir / 'portrait.jpg'),
			relative_path='people/portrait.jpg',
			source_root=source,
			resource_type='image',
			status='completed',
		)

		response = self.client.get(reverse('visuals:home'), {'source': source.id, 'folder': 'travel'})

		self.assertContains(response, 'Mountain')
		self.assertNotContains(response, 'Portrait')

	def test_homepage_shows_sync_status_visuals(self):
		source = SourceRoot.objects.create(
			name='主目录',
			root_path=str(self.temp_dir),
			last_synced_at=timezone.now() - timedelta(minutes=1),
			last_sync_created=3,
			last_sync_updated=1,
			last_sync_missing=2,
		)
		VisualResource.objects.create(
			title='Photo',
			file_path=str(self.temp_dir / 'photo.jpg'),
			relative_path='photo.jpg',
			source_root=source,
			resource_type='image',
			status='completed',
		)

		response = self.client.get(reverse('visuals:home'))

		self.assertContains(response, '最近全局同步')
		self.assertContains(response, '立即同步全部')
		self.assertContains(response, '同步正常')
		self.assertContains(response, '前往 Gallery')
		self.assertContains(response, '上次扫描：新增 3')

	def test_sources_page_shows_management_forms(self):
		source = SourceRoot.objects.create(name='主目录', root_path=str(self.temp_dir), is_enabled=False)

		response = self.client.get(reverse('visuals:sources'), {'edit_source': source.id})

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, '保存并立即扫描')
		self.assertContains(response, '保存更新')
		self.assertContains(response, '移除索引')
		self.assertContains(response, '查看资源')

	def test_sources_page_shows_sync_progress(self):
		source = SourceRoot.objects.create(
			name='扫描中资源源',
			root_path=str(self.temp_dir),
			is_enabled=True,
			is_syncing=True,
			sync_phase='写入索引中',
			sync_progress_total=20,
			sync_progress_scanned=5,
			index_progress_total=10,
			index_progress_processed=3,
			index_progress_completed=2,
			index_progress_failed=1,
			sync_current_path='travel/shot-01.png',
		)

		response = self.client.get(reverse('visuals:sources'))

		self.assertContains(response, '扫描中 1 个')
		self.assertContains(response, '写入索引中')
		self.assertContains(response, '目录 5 / 20')
		self.assertContains(response, '3 / 10')
		self.assertContains(response, '成功 2')
		self.assertContains(response, '失败 1')
		self.assertContains(response, 'travel/shot-01.png')
		self.assertContains(response, 'sources/progress/')

	def test_sources_progress_endpoint_returns_syncing_payload(self):
		source = SourceRoot.objects.create(
			name='同步源',
			root_path=str(self.temp_dir),
			is_enabled=True,
			is_syncing=True,
			sync_phase='等待后台任务',
			sync_progress_total=0,
			sync_progress_scanned=0,
		)

		response = self.client.get(reverse('visuals:sources_progress'))

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload['syncing_count'], 1)
		self.assertEqual(payload['sources'][0]['id'], source.id)
		self.assertTrue(payload['sources'][0]['is_syncing'])
		self.assertEqual(payload['sources'][0]['phase'], '等待后台任务')
		self.assertEqual(payload['sources'][0]['index_total'], 0)

	def test_build_source_tree_uses_priority_sorting_scheme(self):
		now = timezone.now()
		syncing_dir = self.temp_dir / 'syncing'
		error_dir = self.temp_dir / 'error'
		never_dir = self.temp_dir / 'never'
		stale_dir = self.temp_dir / 'stale'
		healthy_dir = self.temp_dir / 'healthy'
		disabled_dir = self.temp_dir / 'disabled'
		for path in [syncing_dir, error_dir, never_dir, stale_dir, healthy_dir, disabled_dir]:
			path.mkdir()
		missing_dir = self.temp_dir / 'missing'

		SourceRoot.objects.create(
			name='健康源',
			root_path=str(healthy_dir),
			is_enabled=True,
			last_synced_at=now,
		)
		SourceRoot.objects.create(
			name='停用源',
			root_path=str(disabled_dir),
			is_enabled=False,
			last_synced_at=now,
		)
		SourceRoot.objects.create(
			name='滞后源',
			root_path=str(stale_dir),
			is_enabled=True,
			last_synced_at=now - timedelta(hours=1),
		)
		SourceRoot.objects.create(
			name='异常源',
			root_path=str(error_dir),
			is_enabled=True,
			last_synced_at=now - timedelta(minutes=5),
			last_sync_error='boom',
		)
		SourceRoot.objects.create(
			name='缺失源',
			root_path=str(missing_dir),
			is_enabled=True,
			last_synced_at=now - timedelta(minutes=3),
		)
		SourceRoot.objects.create(
			name='首次源',
			root_path=str(never_dir),
			is_enabled=True,
		)
		SourceRoot.objects.create(
			name='扫描源',
			root_path=str(syncing_dir),
			is_enabled=True,
			is_syncing=True,
			sync_started_at=now - timedelta(minutes=1),
		)

		source_tree = views_module._build_source_tree(enabled_only=False)

		self.assertEqual(
			[entry['source'].name for entry in source_tree],
			['扫描源', '缺失源', '异常源', '首次源', '滞后源', '健康源', '停用源'],
		)

	def test_sources_progress_endpoint_returns_sources_in_priority_order(self):
		now = timezone.now()
		healthy_dir = self.temp_dir / 'healthy'
		syncing_dir = self.temp_dir / 'syncing'
		missing_dir = self.temp_dir / 'missing'
		healthy_dir.mkdir()
		syncing_dir.mkdir()

		healthy = SourceRoot.objects.create(
			name='健康源',
			root_path=str(healthy_dir),
			is_enabled=True,
			last_synced_at=now,
		)
		syncing = SourceRoot.objects.create(
			name='扫描源',
			root_path=str(syncing_dir),
			is_enabled=True,
			is_syncing=True,
			sync_phase='等待后台任务',
			sync_started_at=now - timedelta(minutes=1),
		)
		missing = SourceRoot.objects.create(
			name='缺失源',
			root_path=str(missing_dir),
			is_enabled=True,
			last_synced_at=now - timedelta(minutes=2),
		)

		response = self.client.get(reverse('visuals:sources_progress'))

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(
			[item['id'] for item in payload['sources'][:3]],
			[syncing.id, missing.id, healthy.id],
		)

	@patch('visuals.views._get_cached_preview_path')
	def test_preview_resource_card_variant_uses_cached_thumbnail(self, mock_get_cached_preview_path):
		original_path = self.temp_dir / 'large-source.jpg'
		original_path.write_bytes(b'original-image')
		cached_path = self.temp_dir / 'cached-card.jpg'
		cached_path.write_bytes(b'cached-image')
		resource = VisualResource.objects.create(
			title='Large Image',
			file_path=str(original_path),
			resource_type='image',
			status='completed',
		)
		mock_get_cached_preview_path.return_value = str(cached_path)

		response = self.client.get(reverse('visuals:preview_resource', args=[resource.id]), {'variant': 'card'})

		self.assertEqual(response.status_code, 200)
		mock_get_cached_preview_path.assert_called_once_with(resource, str(original_path))
		self.assertEqual(response['Cache-Control'], 'public, max-age=86400')

	@patch('visuals.views.enqueue_source_sync')
	def test_create_source_root_adds_source_and_scans(self, mock_enqueue_source_sync):
		mock_enqueue_source_sync.return_value = True
		source_dir = self.temp_dir / 'library'
		source_dir.mkdir()

		response = self.client.post(
			reverse('visuals:create_source_root'),
			{
				'name': '素材库',
				'root_path': str(source_dir),
				'is_enabled': '1',
			},
		)

		self.assertEqual(response.status_code, 302)
		source = SourceRoot.objects.get(root_path=str(source_dir.resolve()))
		self.assertEqual(source.name, '素材库')
		self.assertTrue(source.is_enabled)
		mock_enqueue_source_sync.assert_called_once_with(source, queue_index=True)

	@patch('visuals.views.enqueue_source_sync')
	def test_create_source_root_supports_multiple_directories(self, mock_enqueue_source_sync):
		mock_enqueue_source_sync.return_value = True
		image_dir = self.temp_dir / 'images'
		model_dir = self.temp_dir / 'models'
		image_dir.mkdir()
		model_dir.mkdir()

		response = self.client.post(
			reverse('visuals:create_source_root'),
			{
				'root_path': f'{image_dir}\n{model_dir}',
				'is_enabled': '1',
			},
		)

		self.assertEqual(response.status_code, 302)
		sources = list(SourceRoot.objects.order_by('name').values_list('name', 'root_path', 'is_enabled'))
		self.assertEqual(
			sources,
			[
				('images', str(image_dir.resolve()), True),
				('models', str(model_dir.resolve()), True),
			],
		)
		self.assertEqual(mock_enqueue_source_sync.call_count, 2)
		mock_enqueue_source_sync.assert_has_calls(
			[
				call(SourceRoot.objects.get(root_path=str(image_dir.resolve())), queue_index=True),
				call(SourceRoot.objects.get(root_path=str(model_dir.resolve())), queue_index=True),
			],
			any_order=True,
		)

	def test_create_source_root_rejects_custom_name_for_multiple_directories(self):
		image_dir = self.temp_dir / 'images'
		model_dir = self.temp_dir / 'models'
		image_dir.mkdir()
		model_dir.mkdir()

		response = self.client.post(
			reverse('visuals:create_source_root'),
			{
				'name': '统一名称',
				'root_path': f'{image_dir}\n{model_dir}',
				'is_enabled': '1',
			},
		)

		self.assertEqual(response.status_code, 400)
		self.assertContains(response, '批量添加多个目录时，请留空显示名称', status_code=400)
		self.assertEqual(SourceRoot.objects.count(), 0)

	@patch('visuals.views.enqueue_source_sync')
	def test_update_source_root_updates_path_and_rescans(self, mock_enqueue_source_sync):
		old_dir = self.temp_dir / 'old-library'
		new_dir = self.temp_dir / 'new-library'
		old_dir.mkdir()
		new_dir.mkdir()
		source = SourceRoot.objects.create(name='素材库', root_path=str(old_dir), is_enabled=True)
		mock_enqueue_source_sync.return_value = True

		response = self.client.post(
			reverse('visuals:update_source_root', args=[source.id]),
			{
				'name': '新素材库',
				'root_path': str(new_dir),
				'is_enabled': '1',
			},
		)

		self.assertEqual(response.status_code, 302)
		source.refresh_from_db()
		self.assertEqual(source.name, '新素材库')
		self.assertEqual(source.root_path, str(new_dir.resolve()))
		self.assertTrue(source.is_enabled)
		mock_enqueue_source_sync.assert_called_once_with(source, queue_index=True)

	@patch('visuals.views.enqueue_source_sync')
	def test_update_source_root_can_disable_without_rescan(self, mock_enqueue_source_sync):
		source_dir = self.temp_dir / 'library'
		source_dir.mkdir()
		source = SourceRoot.objects.create(name='素材库', root_path=str(source_dir), is_enabled=True)

		response = self.client.post(
			reverse('visuals:update_source_root', args=[source.id]),
			{
				'name': '素材库',
				'root_path': str(source_dir),
			},
		)

		self.assertEqual(response.status_code, 302)
		source.refresh_from_db()
		self.assertFalse(source.is_enabled)
		mock_enqueue_source_sync.assert_not_called()

	def test_create_source_root_rejects_missing_path(self):
		missing_dir = self.temp_dir / 'missing-folder'

		response = self.client.post(
			reverse('visuals:create_source_root'),
			{
				'name': '不存在目录',
				'root_path': str(missing_dir),
				'is_enabled': '1',
			},
		)

		self.assertEqual(response.status_code, 400)
		self.assertContains(response, '目录不存在', status_code=400)
		self.assertFalse(SourceRoot.objects.filter(name='不存在目录').exists())

	@patch('visuals.views._open_local_directory_picker')
	def test_pick_source_root_returns_selected_path(self, mock_picker):
		picked_dir = self.temp_dir / 'picked'
		picked_dir.mkdir()
		mock_picker.return_value = str(picked_dir)

		response = self.client.get(reverse('visuals:pick_source_root'))

		self.assertEqual(response.status_code, 200)
		mock_picker.assert_called_once_with(initial_path=None)
		self.assertJSONEqual(response.content, {'ok': True, 'path': str(picked_dir), 'name': 'picked'})

	@patch('visuals.views._open_local_directory_picker')
	def test_pick_source_root_passes_initial_path(self, mock_picker):
		initial_dir = self.temp_dir / 'remembered'
		picked_dir = self.temp_dir / 'picked'
		initial_dir.mkdir()
		picked_dir.mkdir()
		mock_picker.return_value = str(picked_dir)

		response = self.client.get(reverse('visuals:pick_source_root'), {'initial_path': str(initial_dir)})

		self.assertEqual(response.status_code, 200)
		mock_picker.assert_called_once_with(initial_path=str(initial_dir))
		self.assertJSONEqual(response.content, {'ok': True, 'path': str(picked_dir), 'name': 'picked'})

	@patch('visuals.views.subprocess.run')
	def test_open_local_directory_picker_uses_utf8_for_chinese_path(self, mock_run):
		picked_dir = self.temp_dir / '中文素材库'
		picked_dir.mkdir()
		mock_run.return_value = subprocess.CompletedProcess(
			args=['powershell'],
			returncode=0,
			stdout=str(picked_dir),
			stderr='',
		)

		selected_path = views_module._open_local_directory_picker()

		self.assertEqual(selected_path, str(picked_dir.resolve()))
		call_args = mock_run.call_args
		self.assertEqual(call_args.kwargs['encoding'], 'utf-8')
		self.assertTrue(call_args.kwargs['text'])
		self.assertIn('UTF8Encoding', call_args.args[0][-1])

	@patch('visuals.views.subprocess.run')
	def test_open_local_directory_picker_uses_initial_path_when_available(self, mock_run):
		initial_dir = self.temp_dir / 'remembered'
		picked_dir = self.temp_dir / 'picked'
		initial_dir.mkdir()
		picked_dir.mkdir()
		mock_run.return_value = subprocess.CompletedProcess(
			args=['powershell'],
			returncode=0,
			stdout=str(picked_dir),
			stderr='',
		)

		selected_path = views_module._open_local_directory_picker(initial_path=str(initial_dir))

		self.assertEqual(selected_path, str(picked_dir.resolve()))
		self.assertIn(f"SelectedPath = '{str(initial_dir.resolve())}'", mock_run.call_args.args[0][-1])

	def test_delete_source_root_removes_index_only(self):
		source_dir = self.temp_dir / 'delete-me'
		source_dir.mkdir()
		file_path = source_dir / 'keep.gif'
		file_path.write_bytes(MINIMAL_GIF)
		source = SourceRoot.objects.create(name='待删除源', root_path=str(source_dir))
		resource = VisualResource.objects.create(
			title='Keep',
			file_path=str(file_path),
			relative_path='keep.gif',
			source_root=source,
			resource_type='gif',
			status='completed',
		)

		response = self.client.post(reverse('visuals:delete_source_root', args=[source.id]))

		self.assertEqual(response.status_code, 302)
		self.assertFalse(SourceRoot.objects.filter(id=source.id).exists())
		self.assertFalse(VisualResource.objects.filter(id=resource.id).exists())
		self.assertTrue(file_path.exists())

	@patch('visuals.sync._queue_index')
	def test_sync_source_root_records_summary_and_clears_error(self, mock_queue_index):
		source = SourceRoot.objects.create(name='同步源', root_path=str(self.temp_dir), last_sync_error='old error')
		file_path = self.temp_dir / 'clip.gif'
		file_path.write_bytes(MINIMAL_GIF)

		summary = sync_source_root(source, enabled_types=['gif'])

		self.assertEqual(summary['created'], 1)
		source.refresh_from_db()
		self.assertEqual(source.last_sync_created, 1)
		self.assertEqual(source.last_sync_updated, 0)
		self.assertEqual(source.last_sync_queued, 1)
		self.assertEqual(source.last_sync_missing, 0)
		self.assertEqual(source.last_sync_error, '')
		self.assertTrue(source.is_syncing)
		self.assertEqual(source.sync_phase, '等待索引')
		self.assertEqual(source.sync_progress_total, 1)
		self.assertEqual(source.sync_progress_scanned, 1)
		self.assertEqual(source.index_progress_total, 1)
		self.assertEqual(source.index_progress_processed, 0)

	@patch('visuals.tasks._calculate_file_hash', return_value='hash-123')
	def test_run_index_visual_resource_updates_source_index_progress(self, _mock_hash):
		source = SourceRoot.objects.create(
			name='索引源',
			root_path=str(self.temp_dir),
			is_enabled=True,
			is_syncing=True,
			sync_phase='等待索引',
			sync_progress_total=1,
			sync_progress_scanned=1,
			index_progress_total=1,
		)
		file_path = self.temp_dir / 'note.txt'
		file_path.write_text('hello', encoding='utf-8')
		resource = VisualResource.objects.create(
			title='note',
			file_path=str(file_path),
			relative_path='note.txt',
			source_root=source,
			resource_type='other',
			status='pending',
		)

		run_index_visual_resource(resource.id)

		resource.refresh_from_db()
		source.refresh_from_db()
		self.assertEqual(resource.status, 'completed')
		self.assertEqual(source.index_progress_processed, 1)
		self.assertEqual(source.index_progress_completed, 1)
		self.assertEqual(source.index_progress_failed, 0)
		self.assertFalse(source.is_syncing)
		self.assertEqual(source.sync_phase, '扫描完成')

	@patch('visuals.tasks._calculate_file_hash', return_value='hash-image')
	@patch('visuals.tasks.Image.open')
	def test_run_index_visual_resource_ignores_large_image_bomb_warning(self, mock_image_open, _mock_hash):
		warning_type = tasks_module.Image.DecompressionBombWarning
		error_type = tasks_module.Image.DecompressionBombError
		original_max_pixels = tasks_module.Image.MAX_IMAGE_PIXELS
		file_path = self.temp_dir / 'huge.png'
		file_path.write_bytes(b'image-data')
		resource = VisualResource.objects.create(
			title='huge',
			file_path=str(file_path),
			relative_path='huge.png',
			resource_type='image',
			status='pending',
		)

		class _FakeImage:
			size = (16384, 16384)
			def __enter__(self):
				warnings.warn('large image', category=warning_type)
				return self
			def __exit__(self, exc_type, exc, tb):
				return False

		def fake_open(_path):
			if tasks_module.Image.MAX_IMAGE_PIXELS is not None:
				raise error_type('large image blocked')
			return _FakeImage()

		mock_image_open.side_effect = fake_open
		with warnings.catch_warnings():
			warnings.simplefilter('error', category=warning_type)
			run_index_visual_resource(resource.id)

		resource.refresh_from_db()
		self.assertEqual(resource.status, 'completed')
		self.assertEqual(resource.width, 16384)
		self.assertEqual(resource.height, 16384)
		self.assertEqual(tasks_module.Image.MAX_IMAGE_PIXELS, original_max_pixels)

	@patch('visuals.tasks._populate_video_metadata')
	@patch('visuals.tasks._calculate_file_hash', return_value='hash-video')
	@patch('visuals.tasks.subprocess.run')
	def test_run_index_visual_resource_uses_short_video_seek_and_formats_ffmpeg_error(self, mock_subprocess_run, _mock_hash, mock_populate_video_metadata):
		source = SourceRoot.objects.create(name='视频源', root_path=str(self.temp_dir), is_enabled=True)
		file_path = self.temp_dir / 'clip.avi'
		file_path.write_bytes(b'video-data')
		resource = VisualResource.objects.create(
			title='clip',
			file_path=str(file_path),
			relative_path='clip.avi',
			source_root=source,
			resource_type='video',
			status='pending',
		)

		def set_short_duration(target_resource):
			target_resource.duration_seconds = 0.5

		mock_populate_video_metadata.side_effect = set_short_duration
		mock_subprocess_run.side_effect = subprocess.CalledProcessError(
			1,
			['ffmpeg'],
			stderr=(
				b'ffmpeg version 8.1\n'
				b'configuration: --enable-everything\n'
				b'Error while opening encoder\n'
				b'Nothing was written into output file\n'
			),
		)

		run_index_visual_resource(resource.id)

		resource.refresh_from_db()
		self.assertEqual(resource.status, 'failed')
		self.assertEqual(resource.last_error, 'Error while opening encoder\nNothing was written into output file')
		command = mock_subprocess_run.call_args.args[0]
		self.assertIn('-hide_banner', command)
		self.assertEqual(command[command.index('-ss') + 1], '0.25')

	@patch('visuals.views.enqueue_source_sync')
	def test_sync_source_now_posts_task(self, mock_enqueue_source_sync):
		source = SourceRoot.objects.create(name='主目录', root_path=str(self.temp_dir))
		mock_enqueue_source_sync.return_value = True

		response = self.client.post(
			reverse('visuals:sync_source_now', args=[source.id]),
			{'next': reverse('visuals:home')},
		)

		self.assertEqual(response.status_code, 302)
		mock_enqueue_source_sync.assert_called_once_with(source, queue_index=True)

	@patch('visuals.views.run_index_visual_resource')
	@patch('visuals.views.run_sync_source_root')
	def test_sync_resource_now_posts_tasks(self, mock_run_sync_source_root, mock_run_index_visual_resource):
		source = SourceRoot.objects.create(name='主目录', root_path=str(self.temp_dir))
		resource = VisualResource.objects.create(
			title='Clip',
			file_path=str(self.temp_dir / 'clip.mp4'),
			source_root=source,
			resource_type='video',
			status='completed',
		)

		response = self.client.post(
			reverse('visuals:sync_resource_now', args=[resource.id]),
			{'next': reverse('visuals:resource_detail', args=[resource.id])},
		)

		self.assertEqual(response.status_code, 302)
		resource.refresh_from_db()
		mock_run_sync_source_root.assert_called_once_with(source.id, queue_index=False, inline_index=False)
		mock_run_index_visual_resource.assert_called_once_with(resource.id)

	@patch('visuals.views.enqueue_source_sync')
	def test_sync_source_now_shows_success_message(self, mock_enqueue_source_sync):
		source = SourceRoot.objects.create(name='主目录', root_path=str(self.temp_dir))
		mock_enqueue_source_sync.return_value = True

		response = self.client.post(
			reverse('visuals:sync_source_now', args=[source.id]),
			{'next': reverse('visuals:home')},
			follow=True,
		)

		self.assertContains(response, '已加入后台扫描')

	@patch('visuals.sync._queue_index')
	def test_sync_source_root_updates_sync_timestamps_and_marks_missing(self, mock_queue_index):
		source = SourceRoot.objects.create(name='同步源', root_path=str(self.temp_dir))
		file_path = self.temp_dir / 'clip.gif'
		file_path.write_bytes(MINIMAL_GIF)

		summary = sync_source_root(source, enabled_types=['gif'])

		self.assertEqual(summary['created'], 1)
		self.assertEqual(summary['queued'], 1)
		resource = VisualResource.objects.get(file_path=str(file_path))
		self.assertIsNotNone(resource.last_synced_at)
		source.refresh_from_db()
		self.assertIsNotNone(source.last_synced_at)

		file_path.unlink()
		summary = sync_source_root(source, enabled_types=['gif'])

		self.assertEqual(summary['missing'], 1)
		resource.refresh_from_db()
		self.assertTrue(resource.is_missing)

	@patch('visuals.management.commands.sync_visuals_sources.sync_source_root')
	def test_sync_visuals_sources_command_aggregates_enabled_sources(self, mock_sync_source_root):
		source_a = SourceRoot.objects.create(name='A', root_path=str(self.temp_dir / 'a'))
		source_b = SourceRoot.objects.create(name='B', root_path=str(self.temp_dir / 'b'), is_enabled=False)
		source_c = SourceRoot.objects.create(name='C', root_path=str(self.temp_dir / 'c'))

		mock_sync_source_root.side_effect = [
			{'created': 1, 'updated': 2, 'queued': 3, 'missing': 4},
			{'created': 5, 'updated': 6, 'queued': 7, 'missing': 8},
		]

		call_command('sync_visuals_sources', '--no-index')

		self.assertEqual(mock_sync_source_root.call_count, 2)
		called_sources = [call.args[0].name for call in mock_sync_source_root.call_args_list]
		self.assertEqual(called_sources, [source_a.name, source_c.name])
