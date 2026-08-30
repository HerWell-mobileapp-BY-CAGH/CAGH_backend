import json
import base64
import uuid
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from rest_framework.exceptions import PermissionDenied

from apps.appointments.models import Appointment
from apps.midwives.models import MidwifeProfile
from apps.consultations.models import Consultation, VoiceSession
from apps.consultations.services import VoiceCallService
from apps.notifications.models import DeviceToken
from apps.notifications.call_notifications import init_firebase_admin, send_call_offer_push

User = get_user_model()


class VoiceCallBackendTestCase(APITestCase):

    def setUp(self):
        self.patient = User.objects.create_user(
            username="patient_call_test",
            email="patient_call@example.com",
            password="Password123!",
            role="PATIENT"
        )
        self.midwife_user = User.objects.create_user(
            username="midwife_call_test",
            email="midwife_call@example.com",
            password="Password123!",
            role="MIDWIFE"
        )
        self.midwife_profile = MidwifeProfile.objects.create(
            user=self.midwife_user,
            license_number="MID-VOICE-12345"
        )
        self.appointment = Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type="VIRTUAL_VOICE",
            status=Appointment.AppointmentStatus.CONFIRMED,
            scheduled_date="2026-08-30",
            start_time="10:00:00",
            end_time="11:00:00",
            created_by=self.patient,
        )
        self.consultation = Consultation.objects.create(
            appointment=self.appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type=Consultation.ConsultationType.VIRTUAL_VOICE,
            status=Consultation.ConsultationStatus.SCHEDULED
        )
        DeviceToken.objects.create(
            user=self.midwife_user,
            token="fcm_token_midwife_123",
            platform="ANDROID",
            is_active=True
        )
        DeviceToken.objects.create(
            user=self.patient,
            token="fcm_token_patient_123",
            platform="ANDROID",
            is_active=True
        )

    def test_participant_resolution_patient_to_midwife(self):
        is_patient, is_midwife, recipient = VoiceCallService.verify_and_resolve_participants(
            self.consultation, self.patient
        )
        self.assertTrue(is_patient)
        self.assertFalse(is_midwife)
        self.assertEqual(recipient.id, self.midwife_user.id)
        self.assertNotEqual(str(self.patient.id), str(recipient.id))

    def test_participant_resolution_midwife_to_patient(self):
        is_patient, is_midwife, recipient = VoiceCallService.verify_and_resolve_participants(
            self.consultation, self.midwife_user
        )
        self.assertFalse(is_patient)
        self.assertTrue(is_midwife)
        self.assertEqual(recipient.id, self.patient.id)
        self.assertNotEqual(str(self.midwife_user.id), str(recipient.id))

    def test_unauthorized_participant_rejected(self):
        other_user = User.objects.create_user(
            username="unauthorized_user",
            password="Password123!"
        )
        with self.assertRaises(PermissionDenied):
            VoiceCallService.verify_and_resolve_participants(self.consultation, other_user)

    @patch("apps.notifications.call_notifications._firebase_initialized", True)
    @patch("firebase_admin.messaging.send_each_for_multicast")
    def test_start_call_patient_to_midwife_creates_session(self, mock_send):
        mock_send.return_value.success_count = 1
        mock_send.return_value.failure_count = 0

        self.client.force_authenticate(user=self.patient)
        url = f"/api/v1/consultations/{self.consultation.id}/voice-session/start/"
        response = self.client.post(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "RINGING")
        self.assertIn("VOICE-", response.data["session_key"])
        self.assertEqual(response.data["caller_id"], str(self.patient.id))
        self.assertEqual(response.data["recipient_id"], str(self.midwife_user.id))

        session = VoiceSession.objects.filter(consultation=self.consultation).first()
        self.assertIsNotNone(session)
        self.assertEqual(session.status, VoiceSession.VoiceSessionStatus.RINGING)
        self.assertEqual(session.caller, self.patient)

    @patch("apps.notifications.call_notifications._firebase_initialized", True)
    @patch("firebase_admin.messaging.send_each_for_multicast")
    def test_duplicate_start_call_reuses_active_session(self, mock_send):
        mock_send.return_value.success_count = 1
        mock_send.return_value.failure_count = 0

        # First call attempt
        res1 = VoiceCallService.start_call(self.consultation, self.patient)
        session_key1 = res1["session_key"]
        call_count_after_first = mock_send.call_count

        # Second call attempt while first is still RINGING
        res2 = VoiceCallService.start_call(self.consultation, self.patient)
        session_key2 = res2["session_key"]

        self.assertEqual(session_key1, session_key2)
        # Verify duplicate FCM was NOT dispatched
        self.assertEqual(mock_send.call_count, call_count_after_first)
        self.assertEqual(VoiceSession.objects.filter(consultation=self.consultation).count(), 1)

    def test_full_call_lifecycle_start_accept_connect_end(self):
        # 1. Start Call (Patient)
        start_res = VoiceCallService.start_call(self.consultation, self.patient)
        self.assertEqual(start_res["status"], "RINGING")

        # 2. Accept Call (Midwife)
        accept_res, accept_code = VoiceCallService.accept_call(self.consultation, self.midwife_user)
        self.assertEqual(accept_code, status.HTTP_200_OK)
        self.assertEqual(accept_res["status"], "ACCEPTED")
        self.assertIsNotNone(accept_res["agora_token"])

        # 3. Connect Call (Media Audio Active)
        connect_res, connect_code = VoiceCallService.connect_call(self.consultation, self.patient)
        self.assertEqual(connect_code, status.HTTP_200_OK)
        self.assertEqual(connect_res["status"], "ONGOING")

        # 4. End Call
        end_res, end_code = VoiceCallService.end_call(self.consultation, self.patient)
        self.assertEqual(end_code, status.HTTP_200_OK)
        self.assertEqual(end_res["status"], "ENDED")

        session = VoiceSession.objects.get(session_key=start_res["session_key"])
        self.assertEqual(session.status, VoiceSession.VoiceSessionStatus.ENDED)
        self.assertIsNotNone(session.ended_at)

    def test_decline_flow_and_idempotency(self):
        # Start Call
        VoiceCallService.start_call(self.consultation, self.patient)

        # First Decline (Midwife)
        dec1, code1 = VoiceCallService.decline_call(self.consultation, self.midwife_user)
        self.assertEqual(code1, status.HTTP_200_OK)
        self.assertEqual(dec1["status"], "DECLINED")

        # Second Decline (Repeat/Idempotent)
        dec2, code2 = VoiceCallService.decline_call(self.consultation, self.midwife_user)
        self.assertEqual(code2, status.HTTP_200_OK)
        self.assertEqual(dec2["status"], "DECLINED")

    def test_illegal_transition_accept_after_end_returns_409(self):
        start_res = VoiceCallService.start_call(self.consultation, self.patient)
        VoiceCallService.end_call(self.consultation, self.patient)

        # Attempt to accept ended call
        acc_res, acc_code = VoiceCallService.accept_call(self.consultation, self.midwife_user)
        self.assertEqual(acc_code, status.HTTP_409_CONFLICT)
        self.assertIn("error", acc_res)

    def test_illegal_transition_accept_after_decline_returns_409(self):
        VoiceCallService.start_call(self.consultation, self.patient)
        VoiceCallService.decline_call(self.consultation, self.midwife_user)

        # Attempt to accept declined call
        acc_res, acc_code = VoiceCallService.accept_call(self.consultation, self.midwife_user)
        self.assertEqual(acc_code, status.HTTP_409_CONFLICT)

    def test_cancel_flow_and_idempotency(self):
        VoiceCallService.start_call(self.consultation, self.patient)

        # Cancel Call (Caller side)
        can1, code1 = VoiceCallService.cancel_call(self.consultation, self.patient)
        self.assertEqual(code1, status.HTTP_200_OK)
        self.assertEqual(can1["status"], "CANCELLED")

        # Second Cancel (Repeat/Idempotent)
        can2, code2 = VoiceCallService.cancel_call(self.consultation, self.patient)
        self.assertEqual(code2, status.HTTP_200_OK)
        self.assertEqual(can2["status"], "CANCELLED")

    def test_fcm_failure_does_not_corrupt_call_state(self):
        # Even if send_call_offer_push fails (e.g. returns None due to FCM error),
        # session MUST remain in RINGING state.
        with patch("apps.notifications.call_notifications.send_call_offer_push") as mock_push:
            mock_push.side_effect = Exception("FCM Network Timeout")

            res = VoiceCallService.start_call(self.consultation, self.patient)
            self.assertEqual(res["status"], "RINGING")

            session = VoiceSession.objects.get(session_key=res["session_key"])
            self.assertEqual(session.status, VoiceSession.VoiceSessionStatus.RINGING)

    def test_firebase_init_handles_raw_json_and_base64(self):
        sample_creds = {
            "type": "service_account",
            "project_id": "cagh-test-proj",
            "private_key_id": "123",
            "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQC...\n-----END PRIVATE KEY-----\n",
            "client_email": "test@cagh-test-proj.iam.gserviceaccount.com"
        }
        json_str = json.dumps(sample_creds)
        b64_str = base64.b64encode(json_str.encode("utf-8")).decode("utf-8")

        with patch("firebase_admin.initialize_app") as mock_init, \
             patch("firebase_admin.credentials.Certificate") as mock_cert:
            mock_app = MagicMock()
            mock_app.project_id = "cagh-test-proj"
            mock_init.return_value = mock_app

            # Test Raw JSON env var
            with patch.dict("os.environ", {"FIREBASE_SERVICE_ACCOUNT_KEY": json_str}):
                with patch("firebase_admin._apps", {}):
                    app = init_firebase_admin()
                    self.assertIsNotNone(app)

            # Test Base64 env var
            with patch.dict("os.environ", {"FIREBASE_SERVICE_ACCOUNT_KEY": b64_str}):
                with patch("firebase_admin._apps", {}):
                    app = init_firebase_admin()
                    self.assertIsNotNone(app)

    def test_agora_token_rejected_for_terminal_call(self):
        start_res = VoiceCallService.start_call(self.consultation, self.patient)
        VoiceCallService.end_call(self.consultation, self.patient)

        token_res, token_code = VoiceCallService.generate_agora_token(self.consultation, self.patient)
        self.assertEqual(token_code, status.HTTP_200_OK)
        self.assertEqual(token_res["agora_token"], "")
        self.assertEqual(token_res["status"], "ENDED")
