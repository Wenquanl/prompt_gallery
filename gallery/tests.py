from django.test import TestCase
from django.urls import reverse


class GalleryNavigationTests(TestCase):
	def test_gallery_home_navbar_contains_visuals_entry(self):
		response = self.client.get(reverse('home'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, reverse('visuals:home'))
		self.assertContains(response, 'Visuals 资源库')
