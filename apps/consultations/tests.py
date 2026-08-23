from datetime import date, timedelta
from django.urls import reverse
from rest_framework import status
from django.utils import timezone
from channels.testing import WebsocketCommunicator
from config.asgi import application
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from apps.midwives.models import MidwifeProfile, Hospital
from apps.appointments.models import Appointment
from apps.consultations.models import Consultation, ConsultationNote, VoiceSession, VideoSession
from apps.consultations.agora_service import AgoraService, Role as AgoraRole
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

        bad_res = self.client.post(url, {"appointment": str(self.pending_appointment.id)}, format="json")
        self.assertEqual(bad_res.status_code, status.HTTP_400_BAD_REQUEST)

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

        self.client.force_authenticate(user=self.midwife_user)
        start_url = reverse("consultation-start", kwargs={"pk": consultation.id})
        start_res = self.client.post(start_url)
        self.assertEqual(start_res.status_code, status.HTTP_200_OK)
        self.assertEqual(start_res.data["status"], "RINGING")
        self.assertIn("agora_channel_name", start_res.data)

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

        self.confirmed_appointment.refresh_from_db()
        self.assertEqual(self.confirmed_appointment.status, "COMPLETED")

    def test_agora_rtc_token_generation_service(self):
        token = AgoraService.generate_rtc_token("cagh_voice_VOICE-TEST1234", uid=101, role=AgoraRole.PUBLISHER)
        self.assertTrue(token.startswith("RTC_TOKEN_") or token.startswith("007") or token.startswith("006"))

    def test_voice_session_agora_lifecycle_endpoints(self):
        consultation = Consultation.objects.create(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="VIRTUAL_VOICE",
            status="SCHEDULED",
        )

        # 1. Caller starts call -> RINGING
        self.client.force_authenticate(user=self.patient)
        start_url = reverse("consultation-start", kwargs={"pk": consultation.id})
        res_start = self.client.post(start_url)
        self.assertEqual(res_start.status_code, status.HTTP_200_OK)
        self.assertEqual(res_start.data["status"], "RINGING")

        session = VoiceSession.objects.get(consultation=consultation)
        self.assertEqual(session.status, VoiceSession.VoiceSessionStatus.RINGING)
        self.assertEqual(session.caller, self.patient)

        # 2. Recipient accepts call -> ACCEPTED + Agora token
        self.client.force_authenticate(user=self.midwife_user)
        accept_url = reverse("consultation-voice-session-accept", kwargs={"pk": consultation.id})
        res_accept = self.client.post(accept_url)
        self.assertEqual(res_accept.status_code, status.HTTP_200_OK)
        self.assertEqual(res_accept.data["status"], "ACCEPTED")
        self.assertIn("agora_token", res_accept.data)

        # 3. Connect audio stream -> ONGOING
        connect_url = reverse("consultation-voice-session-connect", kwargs={"pk": consultation.id})
        res_conn = self.client.post(connect_url)
        self.assertEqual(res_conn.status_code, status.HTTP_200_OK)
        self.assertEqual(res_conn.data["status"], "ONGOING")

        # 4. Caller fetches Agora token for active channel
        self.client.force_authenticate(user=self.patient)
        token_url = reverse("consultation-voice-session-token", kwargs={"pk": consultation.id})
        res_token = self.client.get(token_url)
        self.assertEqual(res_token.status_code, status.HTTP_200_OK)
        self.assertIn("agora_token", res_token.data)

        # 5. End call -> ENDED
        end_url = reverse("consultation-voice-session-end", kwargs={"pk": consultation.id})
        res_end = self.client.post(end_url)
        self.assertEqual(res_end.status_code, status.HTTP_200_OK)
        self.assertEqual(res_end.data["status"], "ENDED")

        session.refresh_from_db()
        self.assertEqual(session.status, VoiceSession.VoiceSessionStatus.ENDED)

    def test_race_condition_protection_on_cancel_and_accept(self):
        consultation = Consultation.objects.create(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="VIRTUAL_VOICE",
            status="SCHEDULED",
        )

        self.client.force_authenticate(user=self.patient)
        start_url = reverse("consultation-start", kwargs={"pk": consultation.id})
        self.client.post(start_url)

        # Patient cancels call
        cancel_url = reverse("consultation-voice-session-cancel", kwargs={"pk": consultation.id})
        res_cancel = self.client.post(cancel_url)
        self.assertEqual(res_cancel.status_code, status.HTTP_200_OK)
        self.assertEqual(res_cancel.data["status"], "CANCELLED")

        # Midwife attempts to accept cancelled call (Race condition test)
        self.client.force_authenticate(user=self.midwife_user)
        accept_url = reverse("consultation-voice-session-accept", kwargs={"pk": consultation.id})
        res_accept = self.client.post(accept_url)
        self.assertEqual(res_accept.status_code, status.HTTP_409_CONFLICT)

    def test_fallback_manage_voice_session_status_guard_and_broadcast(self):
        consultation = Consultation.objects.create(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="VIRTUAL_VOICE",
            status="SCHEDULED",
        )

        # 1. Caller starts call via manage_voice_session fallback (POST /voice-session/ with {'action': 'START'})
        self.client.force_authenticate(user=self.patient)
        manage_url = reverse("consultation-manage-voice-session", kwargs={"pk": consultation.id})
        res_start = self.client.post(manage_url, {"action": "START"}, format="json")
        self.assertEqual(res_start.status_code, status.HTTP_200_OK)
        self.assertEqual(res_start.data["status"], "RINGING")

        # 2. Patient cancels call via manage_voice_session fallback
        res_cancel = self.client.post(manage_url, {"action": "CANCEL"}, format="json")
        self.assertEqual(res_cancel.status_code, status.HTTP_200_OK)
        self.assertEqual(res_cancel.data["status"], "CANCELLED")

        # 3. Midwife attempts to accept cancelled call via manage_voice_session fallback -> 409 Conflict
        self.client.force_authenticate(user=self.midwife_user)
        res_accept = self.client.post(manage_url, {"action": "ACCEPT"}, format="json")
        self.assertEqual(res_accept.status_code, status.HTTP_409_CONFLICT)

        # 4. Midwife attempts to decline cancelled call via manage_voice_session fallback -> 409 Conflict
        res_decline = self.client.post(manage_url, {"action": "DECLINE"}, format="json")
        self.assertEqual(res_decline.status_code, status.HTTP_409_CONFLICT)

        # 5. Verify uid returned by fallback endpoint is numeric
        session = VoiceSession.objects.get(consultation=consultation)
        session.status = VoiceSession.VoiceSessionStatus.RINGING
        session.save()

        res_accept_ok = self.client.post(manage_url, {"action": "ACCEPT"}, format="json")
        self.assertEqual(res_accept_ok.status_code, status.HTTP_200_OK)
        self.assertIsInstance(res_accept_ok.data["uid"], int)
        self.assertEqual(res_accept_ok.data["uid"], AgoraService.get_numeric_uid(self.midwife_user.id))

    def test_unauthorized_user_cannot_access_voice_call_token(self):
        consultation = Consultation.objects.create(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="VIRTUAL_VOICE",
            status="SCHEDULED",
        )

        self.client.force_authenticate(user=self.patient)
        start_url = reverse("consultation-start", kwargs={"pk": consultation.id})
        self.client.post(start_url)

        # Unassigned midwife attempts to fetch Agora token (Permission test)
        self.client.force_authenticate(user=self.other_midwife_user)
        token_url = reverse("consultation-voice-session-token", kwargs={"pk": consultation.id})
        res_bad = self.client.get(token_url)
        self.assertEqual(res_bad.status_code, status.HTTP_403_FORBIDDEN)

    def test_only_assigned_midwife_can_add_notes(self):
        consultation = Consultation.objects.create(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="IN_PERSON",
            status="ACTIVE",
        )

        url = reverse("consultation-add-note", kwargs={"pk": consultation.id})

        self.client.force_authenticate(user=self.other_midwife_user)
        bad_res = self.client.post(url, {"note": "Unauthorized note"}, format="json")
        self.assertEqual(bad_res.status_code, status.HTTP_403_FORBIDDEN)

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

        self.client.force_authenticate(user=self.patient)
        url = reverse("consultation-detail", kwargs={"pk": consultation.id})
        del_res = self.client.delete(url)
        self.assertEqual(del_res.status_code, status.HTTP_403_FORBIDDEN)

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
        self.client.force_authenticate(user=self.patient)
        start_url = reverse("consultation-start", kwargs={"pk": self.confirmed_appointment.id})
        res = self.client.post(start_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "RINGING")
        self.assertIsNotNone(res.data["consultation"])

    async def test_websocket_call_signaling(self):
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

        patient_token = str(AccessToken.for_user(self.patient))
        midwife_token = str(AccessToken.for_user(self.midwife_user))

        patient_comm = WebsocketCommunicator(
            application,
            f"/ws/consultation/{consultation.id}/?token={patient_token}"
        )
        midwife_comm = WebsocketCommunicator(
            application,
            f"/ws/consultation/{consultation.id}/?token={midwife_token}"
        )

        connected_p, _ = await patient_comm.connect()
        self.assertTrue(connected_p)

        connected_m, _ = await midwife_comm.connect()
        self.assertTrue(connected_m)

        res_p_peer_joined = await patient_comm.receive_json_from()
        self.assertEqual(res_p_peer_joined["type"], "peer_joined")

        # 1. Patient sends incoming_call -> Midwife receives incoming_call
        await patient_comm.send_json_to({
            "action": "incoming_call",
            "call_type": "VOICE"
        })
        res_offer = await midwife_comm.receive_json_from()
        self.assertEqual(res_offer["type"], "incoming_call")
        self.assertEqual(res_offer["call_type"], "VOICE")

        # 2. Midwife sends call_accepted -> Patient receives call_accepted
        await midwife_comm.send_json_to({
            "action": "call_accepted"
        })
        res_answer = await patient_comm.receive_json_from()
        self.assertEqual(res_answer["type"], "call_accepted")

        # 3. Patient sends toggle_media -> Midwife receives media_state_changed
        await patient_comm.send_json_to({
            "action": "toggle_media",
            "is_muted": True
        })
        res_media = await midwife_comm.receive_json_from()
        self.assertEqual(res_media["type"], "media_state_changed")
        self.assertTrue(res_media["is_muted"])

        await patient_comm.disconnect()
        await midwife_comm.disconnect()
