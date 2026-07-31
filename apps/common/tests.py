from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from apps.users.models import Profile

User = get_user_model()


class LanguageSelectionTestCase(APITestCase):

    def test_list_supported_languages(self):
        url = reverse("language-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["default_language"], "en")
        codes = [lang["code"] for lang in response.data["supported_languages"]]
        self.assertIn("en", codes)
        self.assertIn("am", codes)

    def test_select_amharic_language_unauthenticated(self):
        url = reverse("language-select")
        data = {"language": "am"}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["language"], "am")
        self.assertEqual(response.data["name"], "Amharic")
        self.assertEqual(response.data["native_name"], "አማርኛ")

    def test_select_language_authenticated_user(self):
        user = User.objects.create_user(
            username="lang_user",
            email="lang@example.com",
            password="Password123!",
        )
        Profile.objects.create(user=user, first_name="Test", last_name="User")
        self.client.force_authenticate(user=user)

        url = reverse("language-select")
        data = {"language": "am"}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        user.profile.refresh_from_db()
        self.assertEqual(user.profile.preferred_language, "am")
