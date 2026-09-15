from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from apps.notifications.models import Notification, DeviceToken, NotificationPreference

User = get_user_model()


class NotificationsTestCase(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="notif_user",
            email="notif@example.com",
            password="NotifPassword123!",
        )

        self.notif1 = Notification.objects.create(
            user=self.user,
            title="Appointment Confirmed",
            body="Your consultation is scheduled for tomorrow.",
            type="APPOINTMENT",
            action="APPOINTMENT_CONFIRMED",
            reference_id="APT-12345",
            is_read=False,
        )

        self.notif2 = Notification.objects.create(
            user=self.user,
            title="New Chat Message",
            body="Midwife sent a response.",
            type="CHAT",
            action="CHAT_MESSAGE",
            reference_id="CHAT-67890",
            is_read=False,
        )

    def test_notification_inbox_and_unread_count(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("notification-list")
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["unread_count"], 2)

    def test_mark_as_read_and_mark_all_as_read(self):
        self.client.force_authenticate(user=self.user)

        # Single read
        url = reverse("notification-mark-as-read", kwargs={"pk": self.notif1.id})
        res = self.client.post(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.notif1.refresh_from_db()
        self.assertTrue(self.notif1.is_read)

        # Mark all read
        all_url = reverse("notification-mark-all-as-read")
        all_res = self.client.post(all_url)
        self.assertEqual(all_res.status_code, status.HTTP_200_OK)
        self.assertEqual(all_res.data["marked_read_count"], 1)

    def test_register_device_token_fr029(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("notification-register-device")
        data = {
            "token": "fcm_token_sample_123456789_abcdef",
            "platform": "ANDROID",
        }
        res = self.client.post(url, data, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(DeviceToken.objects.count(), 1)
        self.assertEqual(DeviceToken.objects.first().token, "fcm_token_sample_123456789_abcdef")

    def test_get_and_update_notification_preferences_fr030(self):
        self.client.force_authenticate(user=self.user)
        url = reverse("notification-preferences")

        # Get default preferences
        get_res = self.client.get(url)
        self.assertEqual(get_res.status_code, status.HTTP_200_OK)
        self.assertTrue(get_res.data["enable_push_notifications"])

        # Update preferences
        update_data = {
            "system_announcements": False,
            "pregnancy_menstrual_reminders": True,
        }
        put_res = self.client.put(url, update_data, format="json")
        self.assertEqual(put_res.status_code, status.HTTP_200_OK)
        self.assertFalse(put_res.data["system_announcements"])

    def test_send_call_offer_push_data_only(self):
        import uuid
        from unittest.mock import patch
        from apps.notifications.call_notifications import send_call_offer_push
        caller = User.objects.create_user(username="caller_doc", password="Password123!")
        DeviceToken.objects.create(user=self.user, token="fcm_token_test_123", platform="ANDROID")

        class StubConsultation:
            id = uuid.uuid4()

        with patch("firebase_admin.messaging.send_each_for_multicast") as mock_send:
            mock_send.return_value.success_count = 1
            mock_send.return_value.failure_count = 0
            mock_send.return_value.responses = []

            result = send_call_offer_push(
                caller=caller,
                recipient=self.user,
                consultation=StubConsultation(),
                call_type="VOICE",
                session_key="VOICE-TEST-KEY",
                agora_channel_name="cagh_test_voice_channel",
            )
        self.assertEqual(DeviceToken.objects.filter(user=self.user, is_active=True).count(), 1)

    def test_send_call_offer_push_includes_receiver_identity(self):
        import uuid
        from unittest.mock import patch
        from apps.notifications.call_notifications import send_call_offer_push
        caller = User.objects.create_user(username="caller_doc2", password="Password123!")
        DeviceToken.objects.create(user=self.user, token="fcm_token_test_456", platform="ANDROID")

        class StubConsultation:
            id = uuid.uuid4()

        with patch("apps.notifications.call_notifications._firebase_initialized", True), \
             patch("firebase_admin.messaging.send_each_for_multicast") as mock_send:
            mock_send.return_value.success_count = 1
            mock_send.return_value.failure_count = 0
            mock_send.return_value.responses = []

            send_call_offer_push(
                caller=caller,
                recipient=self.user,
                consultation=StubConsultation(),
                call_type="VOICE",
                session_key="VOICE-TEST-KEY2",
            )

            self.assertTrue(mock_send.called)
            sent_message = mock_send.call_args[0][0]
            self.assertIn('receiver_id', sent_message.data)
            self.assertEqual(sent_message.data['receiver_id'], str(self.user.id))
            self.assertIn('recipient_id', sent_message.data)
            self.assertEqual(sent_message.data['recipient_id'], str(self.user.id))
            self.assertIn('receiver_name', sent_message.data)
            self.assertIn('recipient_name', sent_message.data)

