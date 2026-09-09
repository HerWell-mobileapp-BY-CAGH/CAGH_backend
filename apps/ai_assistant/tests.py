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
        self.assertIn("Menstrual", res.data["response"])
        self.assertIn("safety_result", res.data)
        self.assertEqual(res.data["safety_result"]["level"], "normal")

    def test_emergency_detection_red_flags(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-root-ask")
        data = {"question": "Help, I have severe bleeding and acute abdominal pain!"}
        res = self.client.post(url, data, format="json")

        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("EMERGENCY", res.data["response"])
        self.assertEqual(res.data["safety_result"]["level"], "emergency")

    def test_suggested_questions_endpoint(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-root-suggested-questions")
        res = self.client.get(url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["count"], 4)
        self.assertIn("suggested_questions", res.data)
        self.assertIn("categories", res.data)
        self.assertIn("popular_chips", res.data)

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

    def test_phase1_chat_creates_conversation_and_returns_payload(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-chat")
        data = {"message": "How do I manage period cramps safely at home?"}
        res = self.client.post(url, data, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("conversation_id", res.data)
        self.assertIn("message", res.data)
        self.assertIn("safety", res.data)
        self.assertEqual(res.data["safety"]["level"], "normal")
        self.assertEqual(res.data["message"]["role"], "assistant")

    def test_phase1_chat_emergency_bypass(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-chat")
        data = {"message": "I am pregnant and bleeding heavily right now!"}
        res = self.client.post(url, data, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["safety"]["level"], "emergency")
        self.assertTrue(res.data["safety"]["requires_sos"])
        self.assertTrue(res.data["message"]["is_emergency"])
        self.assertIn("EMERGENCY MEDICAL ALERT", res.data["message"]["content"])

    def test_phase1_chat_follow_up_message(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-chat")
        # 1st message
        res1 = self.client.post(url, {"message": "What is Dual Protection?"}, format="json")
        conv_id = res1.data["conversation_id"]

        # 2nd follow-up message using same conversation_id
        res2 = self.client.post(url, {"conversation_id": conv_id, "message": "How does it protect against STIs?"}, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["conversation_id"], conv_id)

    def test_conversations_list_and_delete(self):
        self.client.force_authenticate(user=self.user)
        chat_url = reverse("ai-chat")
        self.client.post(chat_url, {"message": "Tell me about Iron and Teff."}, format="json")

        # List conversations
        list_url = reverse("ai-conversation-list")
        res_list = self.client.get(list_url)
        self.assertEqual(res_list.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(res_list.data["results"] if "results" in res_list.data else res_list.data), 1)

        # Delete conversation
        conv_id = (res_list.data["results"][0] if "results" in res_list.data else res_list.data[0])["id"]
        detail_url = reverse("ai-conversation-detail", kwargs={"pk": conv_id})
        res_del = self.client.delete(detail_url)
        self.assertEqual(res_del.status_code, status.HTTP_204_NO_CONTENT)

    def test_unauthorized_user_cannot_access_other_user_conversation(self) -> None:
        # Create conversation for user 1
        self.client.force_authenticate(user=self.user)
        res1 = self.client.post(reverse("ai-chat"), {"message": "Private message"}, format="json")
        conv_id = res1.data["conversation_id"]

        # Create user 2 and attempt access
        other_user = User.objects.create_user(username="other_user", email="other@example.com", password="PassWord123!")
        self.client.force_authenticate(user=other_user)

        # Attempt sending message to user 1's conversation
        res_chat = self.client.post(reverse("ai-chat"), {"conversation_id": conv_id, "message": "Hacking conversation"}, format="json")
        self.assertEqual(res_chat.status_code, status.HTTP_400_BAD_REQUEST)

        # Attempt deleting user 1's conversation
        res_del = self.client.delete(reverse("ai-conversation-detail", kwargs={"pk": conv_id}))
        self.assertEqual(res_del.status_code, status.HTTP_404_NOT_FOUND)

    def test_false_positive_educational_questions_are_normal(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-chat")

        # Case 1: What causes bleeding during menstruation?
        res1 = self.client.post(url, {"message": "What causes bleeding during menstruation?"}, format="json")
        self.assertEqual(res1.status_code, status.HTTP_200_OK)
        self.assertEqual(res1.data["safety"]["level"], "normal")

        # Case 2: What are signs of severe bleeding?
        res2 = self.client.post(url, {"message": "What are signs of severe bleeding?"}, format="json")
        self.assertEqual(res2.status_code, status.HTTP_200_OK)
        self.assertEqual(res2.data["safety"]["level"], "normal")

    def test_contextual_emergency(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-chat")
        res = self.client.post(url, {"message": "I am bleeding heavily right now"}, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["safety"]["level"], "emergency")
        self.assertTrue(res.data["safety"]["requires_sos"])

    def test_urgent_safety_tier_behavior(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-chat")
        res = self.client.post(url, {"message": "I have persistent abdominal pain during pregnancy"}, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["safety"]["level"], "urgent")
        self.assertFalse(res.data["safety"]["requires_sos"])
        self.assertEqual(res.data["message"]["safety_level"], "urgent")
        self.assertIn("URGENT CLINICAL ADVISORY", res.data["message"]["content"])

    def test_priority_collision_self_harm_overrides_pregnancy(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-chat")
        # Query contains severe pregnancy bleeding + self harm intent
        res = self.client.post(url, {"message": "I am pregnant, bleeding heavily, and want to kill myself"}, format="json")

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["safety"]["category"], "self_harm")
        self.assertEqual(res.data["safety"]["priority"], 100)

    def test_empty_and_oversized_input_validation(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-chat")

        # Empty message
        res_empty = self.client.post(url, {"message": "   "}, format="json")
        self.assertEqual(res_empty.status_code, status.HTTP_400_BAD_REQUEST)

        # Oversized message (>1000 chars)
        res_large = self.client.post(url, {"message": "A" * 1050}, format="json")
        self.assertEqual(res_large.status_code, status.HTTP_400_BAD_REQUEST)

    def test_invalid_and_deleted_conversation_id_handled(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-chat")

        # Invalid UUID
        res_invalid = self.client.post(url, {"conversation_id": "00000000-0000-0000-0000-000000000000", "message": "Hello"}, format="json")
        self.assertEqual(res_invalid.status_code, status.HTTP_400_BAD_REQUEST)

        # Create and delete a conversation, then attempt continuation
        res_init = self.client.post(url, {"message": "Initial message"}, format="json")
        conv_id = res_init.data["conversation_id"]
        self.client.delete(reverse("ai-conversation-detail", kwargs={"pk": conv_id}))

        res_deleted = self.client.post(url, {"conversation_id": conv_id, "message": "Continuation"}, format="json")
        self.assertEqual(res_deleted.status_code, status.HTTP_400_BAD_REQUEST)

    def test_safety_validation_blocks_unsafe_provider_output(self):
        from apps.ai_assistant.services import SafetyValidationService
        unsafe_text = "You have cervical cancer and diagnosed with HIV. Take 500 mg pill."
        validated = SafetyValidationService.validate_response(unsafe_text)
        self.assertNotIn("diagnosed with HIV", validated)
        self.assertIn("Educational Health Guidance", validated)

    def test_provider_failure_resilience(self):
        from unittest.mock import patch
        self.client.force_authenticate(user=self.user)
        url = reverse("ai-chat")

        with patch("apps.ai_assistant.services.response_service.KnowledgeResponseProvider.generate_response", side_effect=RuntimeError("Provider offline")):
            res = self.client.post(url, {"message": "How do I take iron supplements?"}, format="json")
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertIn("Educational Health Guidance", res.data["message"]["content"])
