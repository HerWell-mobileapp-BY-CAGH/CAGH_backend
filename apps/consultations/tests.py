from datetime import date, timedelta
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from apps.midwives.models import MidwifeProfile, Hospital
from apps.appointments.models import Appointment
from apps.consultations.models import Consultation, ConsultationNote, VoiceSession, VideoSession
from apps.notifications.models import Notification

User = get_user_model()


class ConsultationManagementTestCase(APITestCase):

    def setUp(self):
        # Patient
        self.patient = User.objects.create_user(
            username="patient_consult",
            email="patient_c@example.com",
            password="PatientPassword123!",
            role="PATIENT",
        )

        # Assigned Midwife
        self.midwife_user = User.objects.create_user(
            username="midwife_consult",
            email="midwife_c@example.com",
            password="MidwifePassword123!",
            role="MIDWIFE",
        )
        self.hospital = Hospital.objects.create(name="Central Hospital", address="Addis Ababa")
        self.midwife_profile = MidwifeProfile.objects.create(
            user=self.midwife_user,
            hospital=self.hospital,
            license_number="MW-CONS-200",
            verification_status="APPROVED",
        )

        # Other Midwife (Unassigned)
        self.other_midwife_user = User.objects.create_user(
            username="other_midwife",
            email="other_m@example.com",
            password="OtherPassword123!",
            role="MIDWIFE",
        )
        self.other_midwife_profile = MidwifeProfile.objects.create(
            user=self.other_midwife_user,
            hospital=self.hospital,
            license_number="MW-CONS-201",
            verification_status="APPROVED",
        )

        # Confirmed Appointment
        self.confirmed_appointment = Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type="VIRTUAL_VOICE",
            scheduled_date=date.today(),
            start_time="14:00:00",
            end_time="14:30:00",
            status="CONFIRMED",
            created_by=self.patient,
        )

        # Pending Appointment
        self.pending_appointment = Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type="IN_PERSON",
            scheduled_date=date.today() + timedelta(days=1),
            start_time="10:00:00",
            end_time="10:30:00",
            status="PENDING",
            created_by=self.patient,
        )

    def test_create_consultation_requires_confirmed_appointment(self):
        self.client.force_authenticate(user=self.patient)
        url = reverse("consultation-list")

        # Try with pending appointment (Rule 2)
        bad_res = self.client.post(url, {"appointment": str(self.pending_appointment.id)}, format="json")
        self.assertEqual(bad_res.status_code, status.HTTP_400_BAD_REQUEST)

        # Try with confirmed appointment
        good_res = self.client.post(url, {"appointment": str(self.confirmed_appointment.id)}, format="json")
        self.assertEqual(good_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(good_res.data["consultation_type"], "VIRTUAL_VOICE")
        self.assertEqual(good_res.data["status"], "SCHEDULED")

    def test_consultation_start_and_completion_lifecycle(self):
        consultation = Consultation.objects.create(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="VIRTUAL_VOICE",
            status="SCHEDULED",
        )

        # Start consultation
        self.client.force_authenticate(user=self.midwife_user)
        start_url = reverse("consultation-start", kwargs={"pk": consultation.id})
        start_res = self.client.post(start_url)
        self.assertEqual(start_res.status_code, status.HTTP_200_OK)
        self.assertEqual(start_res.data["status"], "ACTIVE")

        # Complete consultation with summary & diagnosis
        complete_url = reverse("consultation-complete", kwargs={"pk": consultation.id})
        complete_data = {
            "summary": "Patient presented for maternal consultation. Vital signs normal.",
            "diagnosis": "Healthy pregnancy progression.",
            "recommendation": "Maintain iron & folic acid supplementation.",
            "follow_up_required": True,
            "follow_up_date": (date.today() + timedelta(days=14)).strftime("%Y-%m-%d"),
        }
        comp_res = self.client.post(complete_url, complete_data, format="json")
        self.assertEqual(comp_res.status_code, status.HTTP_200_OK)
        self.assertEqual(comp_res.data["status"], "COMPLETED")

        # Verify linked appointment status updated to COMPLETED
        self.confirmed_appointment.refresh_from_db()
        self.assertEqual(self.confirmed_appointment.status, "COMPLETED")

    def test_only_assigned_midwife_can_add_notes(self):
        consultation = Consultation.objects.create(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="IN_PERSON",
            status="ACTIVE",
        )

        url = reverse("consultation-add-note", kwargs={"pk": consultation.id})

        # Unassigned midwife attempts to add note (Rule 3)
        self.client.force_authenticate(user=self.other_midwife_user)
        bad_res = self.client.post(url, {"note": "Unauthorized note"}, format="json")
        self.assertEqual(bad_res.status_code, status.HTTP_403_FORBIDDEN)

        # Assigned midwife adds note
        self.client.force_authenticate(user=self.midwife_user)
        good_res = self.client.post(url, {"note": "Patient exhibits excellent health markers."}, format="json")
        self.assertEqual(good_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ConsultationNote.objects.count(), 1)

    def test_consultation_cannot_be_permanently_deleted(self):
        consultation = Consultation.objects.create(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="IN_PERSON",
            status="COMPLETED",
        )

        # Attempt DELETE (Rule 4)
        self.client.force_authenticate(user=self.patient)
        url = reverse("consultation-detail", kwargs={"pk": consultation.id})
        del_res = self.client.delete(url)
        self.assertEqual(del_res.status_code, status.HTTP_403_FORBIDDEN)

    def test_voice_and_video_session_management(self):
        consultation = Consultation.objects.create(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="VIRTUAL_VOICE",
            status="ACTIVE",
        )

        self.client.force_authenticate(user=self.midwife_user)

        # Voice session start & end
        voice_url = reverse("consultation-manage-voice-session", kwargs={"pk": consultation.id})
        start_res = self.client.post(voice_url, {"action": "START"}, format="json")
        self.assertEqual(start_res.status_code, status.HTTP_200_OK)
        self.assertEqual(start_res.data["status"], "ONGOING")

        end_res = self.client.post(voice_url, {"action": "END"}, format="json")
        self.assertEqual(end_res.status_code, status.HTTP_200_OK)
        self.assertEqual(end_res.data["status"], "ENDED")

    def test_active_and_history_endpoints(self):
        Consultation.objects.create(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="VIRTUAL_VOICE",
            status="ACTIVE",
        )

        self.client.force_authenticate(user=self.patient)
        active_url = reverse("consultation-active")
        res = self.client.get(active_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertTrue(res.data["active"])

        history_url = reverse("consultation-history")
        hist_res = self.client.get(history_url)
        self.assertEqual(hist_res.status_code, status.HTTP_200_OK)

    def test_start_call_using_appointment_id(self):
        """Verifies starting a call using Appointment ID directly creates consultation & triggers call."""
        self.client.force_authenticate(user=self.patient)
        start_url = reverse("consultation-start", kwargs={"pk": self.confirmed_appointment.id})
        res = self.client.post(start_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "ACTIVE")
        self.assertIsNotNone(res.data["consultation"])

    async def test_websocket_call_signaling(self):
        """Verifies WebSocket WebRTC call signaling: call_offer, call_answer, ice_candidate, toggle_media, end_call."""
        from rest_framework_simplejwt.tokens import AccessToken
        from channels.testing import WebsocketCommunicator
        from config.asgi import application

        consultation = await Consultation.objects.acreate(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="VIRTUAL_VOICE",
            status="ACTIVE",
        )

        token = str(AccessToken.for_user(self.patient))
        communicator = WebsocketCommunicator(
            application,
            f"/ws/consultation/{consultation.id}/?token={token}"
        )
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        # 1. Send call_offer
        await communicator.send_json_to({
            "action": "call_offer",
            "call_type": "VOICE",
            "sdp_offer": "dummy_sdp_offer_data",
            "rtc_token": "dummy_rtc_token"
        })
        res_offer = await communicator.receive_json_from()
        self.assertEqual(res_offer["type"], "incoming_call_offer")
        self.assertEqual(res_offer["call_type"], "VOICE")

        # 2. Send call_answer
        await communicator.send_json_to({
            "action": "call_answer",
            "sdp_answer": "dummy_sdp_answer_data"
        })
        res_answer = await communicator.receive_json_from()
        self.assertEqual(res_answer["type"], "call_answered")

        # 3. Send toggle_media (mute mic)
        await communicator.send_json_to({
            "action": "toggle_media",
            "is_muted": True
        })
        res_media = await communicator.receive_json_from()
        self.assertEqual(res_media["type"], "media_state_changed")
        self.assertTrue(res_media["is_muted"])

        await communicator.disconnect()

