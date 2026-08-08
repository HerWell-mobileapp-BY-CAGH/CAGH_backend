from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from apps.ai_assistant.models import AIQuestion

User = get_user_model()


class AIAssistantTestCase(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="ai_user",
            email="ai@example.com",
            password="AIPassword123!",
        )

    def test_ask_health_question_and_safety_disclaimer(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-root-ask")
        data = {"question": "How can I relieve period cramps naturally?"}
        res = self.client.post(url, data, format="json")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("response", res.data)
        self.assertIn("disclaimer", res.data)
        self.assertIn("Menstrual Health", res.data["response"])

    def test_emergency_detection_red_flags(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-root-ask")
        data = {"question": "Help, I have severe bleeding and acute abdominal pain!"}
        res = self.client.post(url, data, format="json")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("EMERGENCY ALERT", res.data["response"])

    def test_suggested_questions_endpoint(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-root-suggested-questions")
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 5)
        self.assertIn("suggested_questions", res.data)

    def test_thumbs_up_thumbs_down_feedback(self):
        self.client.force_authenticate(user=self.user)
        ai_q = AIQuestion.objects.create(
            user=self.user,
            question="What vitamins should I take during pregnancy?",
            response="Folic acid and iron are recommended.",
        )

        url = reverse("ai-root-feedback", kwargs={"pk": ai_q.id})

        # Thumbs up
        res_up = self.client.post(url, {"feedback": "THUMBS_UP"}, format="json")
        self.assertEqual(res_up.status_code, status.HTTP_200_OK)
        self.assertEqual(res_up.data["feedback"], "THUMBS_UP")

        # Thumbs down
        res_down = self.client.post(url, {"feedback": "THUMBS_DOWN"}, format="json")
        self.assertEqual(res_down.status_code, status.HTTP_200_OK)
        self.assertEqual(res_down.data["feedback"], "THUMBS_DOWN")
