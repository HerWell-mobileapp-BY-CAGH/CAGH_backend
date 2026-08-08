from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from apps.midwives.models import MidwifeProfile, Hospital
from apps.chat.models import ChatRoom, Message, Attachment
from apps.notifications.models import Notification

User = get_user_model()


class ChatSystemTestCase(APITestCase):

    def setUp(self):
        # Patient
        self.patient = User.objects.create_user(
            username="patient_chat",
            email="patient_chat@example.com",
            password="PatientPassword123!",
            role="PATIENT",
        )

        # Midwife
        self.midwife_user = User.objects.create_user(
            username="midwife_chat",
            email="midwife_chat@example.com",
            password="MidwifePassword123!",
            role="MIDWIFE",
        )
        self.hospital = Hospital.objects.create(name="St. Paul Hospital", address="Addis Ababa")
        self.midwife_profile = MidwifeProfile.objects.create(
            user=self.midwife_user,
            hospital=self.hospital,
            license_number="MW-CHAT-300",
            verification_status="APPROVED",
        )

    def test_chat_request_creation_and_acceptance_workflow(self):
        self.client.force_authenticate(user=self.patient)

        # 1. User sends chat request (FR-014 workflow)
        url = reverse("chat-room-list")
        req_data = {
            "midwife": str(self.midwife_profile.id),
            "initial_message": "Hello Midwife, I have a quick question about nutrition.",
        }
        res = self.client.post(url, req_data, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        room_id = res.data["id"]
        self.assertEqual(res.data["status"], "REQUESTED")

        # Verify Midwife received Notification
        midwife_notifs = Notification.objects.filter(user=self.midwife_user, type="CHAT")
        self.assertTrue(midwife_notifs.exists())

        # 2. Try sending message before midwife accepts (Must fail)
        msg_url = reverse("chat-room-messages", kwargs={"pk": room_id})
        fail_msg_res = self.client.post(msg_url, {"content": "Can you reply?"}, format="json")
        self.assertEqual(fail_msg_res.status_code, status.HTTP_400_BAD_REQUEST)

        # 3. Midwife accepts chat request
        self.client.force_authenticate(user=self.midwife_user)
        accept_url = reverse("chat-room-accept", kwargs={"pk": room_id})
        acc_res = self.client.post(accept_url)
        self.assertEqual(acc_res.status_code, status.HTTP_200_OK)
        self.assertEqual(acc_res.data["status"], "ACCEPTED")

        # 4. Both parties communicate freely
        self.client.force_authenticate(user=self.patient)
        msg_res = self.client.post(msg_url, {"content": "Thank you for accepting!"}, format="json")
        self.assertEqual(msg_res.status_code, status.HTTP_201_CREATED)

    def test_attachments_image_pdf_voice_note(self):
        room = ChatRoom.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            status="ACCEPTED",
        )

        self.client.force_authenticate(user=self.patient)
        msg_url = reverse("chat-room-messages", kwargs={"pk": room.id})

        # Image Attachment
        img_res = self.client.post(msg_url, {
            "content": "Lab report image",
            "message_type": "IMAGE",
            "file_url": "https://cagh.org/media/reports/lab1.png",
            "file_type": "image/png",
            "file_size": 204800,
        }, format="json")
        self.assertEqual(img_res.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(img_res.data["attachment"])

        # Voice Note Attachment
        voice_res = self.client.post(msg_url, {
            "content": "Voice inquiry",
            "message_type": "VOICE_NOTE",
            "file_url": "https://cagh.org/media/audio/voice1.mp3",
            "file_type": "audio/mp3",
            "file_size": 51200,
        }, format="json")
        self.assertEqual(voice_res.status_code, status.HTTP_201_CREATED)

    def test_read_receipts(self):
        room = ChatRoom.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            status="ACCEPTED",
        )
        msg = Message.objects.create(
            chat_room=room,
            sender=self.patient,
            content="Hello midwife",
            status="SENT",
        )

        # Midwife opens chat room and marks messages as read
        self.client.force_authenticate(user=self.midwife_user)
        read_url = reverse("chat-room-read", kwargs={"pk": room.id})
        res = self.client.post(read_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["marked_read_count"], 1)

        msg.refresh_from_db()
        self.assertEqual(msg.status, "READ")
        self.assertIsNotNone(msg.read_at)

    def test_chat_room_search(self):
        room = ChatRoom.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            status="ACCEPTED",
        )
        Message.objects.create(
            chat_room=room,
            sender=self.midwife_user,
            content="How are you feeling today?",
            status="SENT",
        )

        self.client.force_authenticate(user=self.patient)
        list_url = reverse("chat-room-list")

        # Search by midwife username
        res = self.client.get(f"{list_url}?search=midwife_chat")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data.get("results", res.data)
        self.assertEqual(len(results), 1)

        # Search by message content
        res_msg = self.client.get(f"{list_url}?search=feeling")
        self.assertEqual(res_msg.status_code, status.HTTP_200_OK)
        results_msg = res_msg.data.get("results", res_msg.data)
        self.assertEqual(len(results_msg), 1)
