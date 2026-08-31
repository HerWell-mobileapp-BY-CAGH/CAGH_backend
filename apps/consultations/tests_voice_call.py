import json
import base64
import uuid
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from rest_framework.exceptions import PermissionDenied, ValidationError
from channels.testing import WebsocketCommunicator

from apps.appointments.models import Appointment
from apps.midwives.models import MidwifeProfile
from apps.consultations.models import Consultation, VoiceSession
from apps.consultations.services import VoiceCallService
from apps.consultations.consumers import UserCallConsumer
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

    @patch("channels.layers.InMemoryChannelLayer.group_send")
    def test_ws_call_offer_dispatched_to_receiver_group(self, mock_group_send):
        # Test 1, 2, 3: Dispatches call_offer to user_calls_<receiver.id> with canonical payload
        start_res = VoiceCallService.start_call(self.consultation, self.patient)
        self.assertEqual(start_res["status"], "RINGING")

        expected_group = f"user_calls_{self.midwife_user.id}"

        # Find the group_send call for user_calls_<receiver_id>
        target_calls = [
            call_args for call_args in mock_group_send.call_args_list
            if call_args[0][0] == expected_group
        ]
        self.assertTrue(len(target_calls) >= 1)

        payload = target_calls[0][0][1]
        self.assertEqual(payload["type"], "call_signal")
        self.assertEqual(payload["action"], "call_offer")
        self.assertEqual(payload["event"], "VOICE_SESSION_CREATED")
        self.assertEqual(payload["call_id"], start_res["session_key"])
        self.assertEqual(payload["consultation_id"], str(self.consultation.id))
        self.assertEqual(payload["caller_id"], str(self.patient.id))
        self.assertEqual(payload["receiver_id"], str(self.midwife_user.id))

    @patch("channels.layers.InMemoryChannelLayer.group_send")
    def test_exactly_one_call_offer_dispatched(self, mock_group_send):
        # Test 8: group_send with action == "call_offer" happens exactly once
        VoiceCallService.start_call(self.consultation, self.patient)

        offer_calls = [
            call_args for call_args in mock_group_send.call_args_list
            if isinstance(call_args[0][1], dict) and call_args[0][1].get("action") == "call_offer"
        ]
        self.assertEqual(len(offer_calls), 1)

    async def test_user_call_consumer_receives_and_delivers_call_offer(self):
        # Test 4: Consumer receives call_signal and sends text frame
        communicator = WebsocketCommunicator(UserCallConsumer.as_asgi(), "/ws/user-calls/")
        communicator.scope["user"] = self.midwife_user

        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        from channels.layers import get_channel_layer
        channel_layer = get_channel_layer()

        test_event = {
            "type": "call_signal",
            "action": "call_offer",
            "event": "VOICE_SESSION_CREATED",
            "call_id": "VOICE-TEST123456",
            "consultation_id": str(self.consultation.id),
            "caller_id": str(self.patient.id),
            "receiver_id": str(self.midwife_user.id),
            "caller_name": "Test Caller",
            "call_type": "VOICE"
        }

        await channel_layer.group_send(f"user_calls_{self.midwife_user.id}", test_event)

        response = await communicator.receive_json_from()
        self.assertEqual(response["action"], "call_offer")
        self.assertEqual(response["event"], "VOICE_SESSION_CREATED")
        self.assertEqual(response["call_id"], "VOICE-TEST123456")
        self.assertEqual(response["caller_id"], str(self.patient.id))

        await communicator.disconnect()

    @patch("channels.layers.InMemoryChannelLayer.group_send")
    def test_decline_and_end_signal_dispatched_to_user_calls(self, mock_group_send):
        # Test 5 & 6: Decline and End signals reach target recipient
        VoiceCallService.start_call(self.consultation, self.patient)
        mock_group_send.reset_mock()

        # Decline active call
        VoiceCallService.decline_call(self.consultation, self.midwife_user)
        decline_calls = [
            call_args for call_args in mock_group_send.call_args_list
            if call_args[0][0] == f"user_calls_{self.patient.id}"
        ]
        self.assertTrue(len(decline_calls) >= 1)
        self.assertEqual(decline_calls[0][0][1]["action"], "call_declined")

        # Start a new call for testing end_call
        VoiceSession.objects.filter(consultation=self.consultation).update(status=VoiceSession.VoiceSessionStatus.ENDED)
        VoiceCallService.start_call(self.consultation, self.patient)
        mock_group_send.reset_mock()

        # End active call
        VoiceCallService.end_call(self.consultation, self.patient)
        end_calls = [
            call_args for call_args in mock_group_send.call_args_list
            if call_args[0][0] == f"user_calls_{self.midwife_user.id}"
        ]
        self.assertTrue(len(end_calls) >= 1)
        self.assertEqual(end_calls[0][0][1]["action"], "call_ended")

    @patch("apps.notifications.call_notifications._firebase_initialized", False)
    @patch("channels.layers.InMemoryChannelLayer.group_send")
    def test_firebase_uninitialized_does_not_prevent_ws_call_offer(self, mock_group_send):
        # Test 7: Firebase failure/skipped state DOES NOT prevent WS offer
        res = VoiceCallService.start_call(self.consultation, self.patient)
        self.assertEqual(res["status"], "RINGING")

        offer_calls = [
            call_args for call_args in mock_group_send.call_args_list
            if call_args[0][0] == f"user_calls_{self.midwife_user.id}"
        ]
        self.assertEqual(len(offer_calls), 1)

    def test_self_call_rejected_before_session_creation(self):
        # Attempt to call self (consultation user == midwife user)
        patient_midwife_profile = MidwifeProfile.objects.create(
            user=self.patient,
            license_number="MID-PATIENT-999"
        )
        self_appointment = Appointment.objects.create(
            user=self.patient,
            midwife=patient_midwife_profile,
            appointment_type="VIRTUAL_VOICE",
            status=Appointment.AppointmentStatus.CONFIRMED,
            scheduled_date="2026-08-30",
            start_time="10:00:00",
            end_time="11:00:00",
            created_by=self.patient,
        )
        same_user_consultation = Consultation.objects.create(
            appointment=self_appointment,
            user=self.patient,
            midwife=patient_midwife_profile,
            status=Consultation.ConsultationStatus.SCHEDULED
        )
        with self.assertRaises(ValidationError):
            VoiceCallService.start_call(same_user_consultation, self.patient)

        # Verify no VoiceSession was created
        self.assertFalse(VoiceSession.objects.filter(consultation=same_user_consultation).exists())

    @patch("apps.notifications.call_notifications._firebase_initialized", False)
    def test_a_firebase_credentials_missing_does_not_crash_voice_session(self):
        # Test A: Firebase missing/unavailable does not crash VoiceSession creation
        res = VoiceCallService.start_call(self.consultation, self.patient)
        self.assertEqual(res["status"], "RINGING")
        session = VoiceSession.objects.get(session_key=res["session_key"])
        self.assertEqual(session.status, VoiceSession.VoiceSessionStatus.RINGING)

    def test_b_firebase_initialization_succeeds_with_project_id(self):
        # Test B: Mock Firebase Admin initialization succeeds with project ID
        sample_creds = {
            "type": "service_account",
            "project_id": "cagh-bd916",
            "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBg...\n-----END PRIVATE KEY-----\n",
            "client_email": "test@cagh-bd916.iam.gserviceaccount.com"
        }
        json_str = json.dumps(sample_creds)
        with patch("firebase_admin.initialize_app") as mock_init, \
             patch("firebase_admin.credentials.Certificate") as mock_cert, \
             patch.dict("os.environ", {"FIREBASE_SERVICE_ACCOUNT_KEY": json_str}), \
             patch("firebase_admin._apps", {}):
            mock_app = MagicMock(project_id="cagh-bd916")
            mock_init.return_value = mock_app
            app = init_firebase_admin()
            self.assertIsNotNone(app)
            self.assertEqual(getattr(app, "project_id", None), "cagh-bd916")

    @patch("apps.notifications.call_notifications._firebase_initialized", True)
    @patch("firebase_admin.messaging.send_each_for_multicast")
    def test_c_fcm_send_succeeds_multicast(self, mock_send):
        # Test C: FCM send succeeds, mock multicast response with success_count=1
        mock_response = MagicMock()
        mock_response.success_count = 1
        mock_response.failure_count = 0
        mock_response.responses = []
        mock_send.return_value = mock_response

        res = send_call_offer_push(
            caller=self.patient,
            recipient=self.midwife_user,
            consultation=self.consultation,
            call_type="VOICE",
            session_key="VOICE-TEST-FCM-123",
        )
        self.assertIsNotNone(res)
        self.assertEqual(res.success_count, 1)

    @patch("apps.notifications.call_notifications._firebase_initialized", True)
    @patch("firebase_admin.messaging.send_each_for_multicast")
    def test_d_firebase_send_failure_logged_safely(self, mock_send):
        # Test D: FCM send failure logged safely without breaking WS call flow
        mock_send.side_effect = Exception("FCM Transport Unavailable")

        # WS call offer dispatch must still succeed even when FCM throws exception
        start_res = VoiceCallService.start_call(self.consultation, self.patient)
        self.assertEqual(start_res["status"], "RINGING")

    def test_e_existing_firebase_app_reused_without_duplicate_app_error(self):
        # Test E: Existing initialized [DEFAULT] Firebase app reused without duplicate error
        mock_app = MagicMock(project_id="cagh-bd916")
        with patch("firebase_admin._apps", {"[DEFAULT]": mock_app}), \
             patch("firebase_admin.get_app", return_value=mock_app):
            app = init_firebase_admin()
            self.assertEqual(app, mock_app)

    def test_f_escaped_private_key_normalized(self):
        # Test F: Escaped \n in private_key string normalized to real \n newlines
        from apps.notifications.call_notifications import validate_firebase_credentials
        raw_creds = {
            "type": "service_account",
            "project_id": "cagh-bd916",
            "private_key": "-----BEGIN PRIVATE KEY-----\\nMIIEvgIBADANBgk...\\n-----END PRIVATE KEY-----\\n",
            "client_email": "test@cagh-bd916.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
        is_valid, reason, normalized = validate_firebase_credentials(raw_creds)
        self.assertTrue(is_valid)
        self.assertIn("\n", normalized["private_key"])
        self.assertNotIn("\\n", normalized["private_key"])

    @patch("firebase_admin.get_app")
    def test_g_invalid_json_fails_safely(self, mock_get_app):
        # Test G: Invalid JSON string produces safe parse error without crashing
        mock_get_app.side_effect = ValueError("No app exists")
        with patch.dict("os.environ", {"FIREBASE_SERVICE_ACCOUNT_KEY": "{invalid_json_str"}), \
             patch("firebase_admin._apps", {}), \
             patch("apps.notifications.call_notifications._firebase_initialized", False):
            app = init_firebase_admin()
            self.assertIsNone(app)

    @patch("firebase_admin.get_app")
    def test_h_missing_required_fields_fails_safely(self, mock_get_app):
        # Test H: Valid JSON missing required schema fields produces safe parse error
        mock_get_app.side_effect = ValueError("No app exists")
        incomplete_json = json.dumps({"type": "service_account", "project_id": "cagh-bd916"})
        with patch.dict("os.environ", {"FIREBASE_SERVICE_ACCOUNT_KEY": incomplete_json}), \
             patch("firebase_admin._apps", {}), \
             patch("apps.notifications.call_notifications._firebase_initialized", False):
            app = init_firebase_admin()
            self.assertIsNone(app)

    def test_i_base64_json_credentials_initialize(self):
        # Test I: Base64-encoded JSON credentials initialize successfully
        sample_creds = {
            "type": "service_account",
            "project_id": "cagh-bd916",
            "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBg...\n-----END PRIVATE KEY-----\n",
            "client_email": "test@cagh-bd916.iam.gserviceaccount.com",
            "token_uri": "https://oauth2.googleapis.com/token"
        }
        b64_str = base64.b64encode(json.dumps(sample_creds).encode('utf-8')).decode('utf-8')
        with patch("firebase_admin.initialize_app") as mock_init, \
             patch("firebase_admin.credentials.Certificate") as mock_cert, \
             patch.dict("os.environ", {"FIREBASE_SERVICE_ACCOUNT_KEY": b64_str}), \
             patch("firebase_admin._apps", {}):
            mock_app = MagicMock(project_id="cagh-bd916")
            mock_init.return_value = mock_app
            app = init_firebase_admin()
            self.assertIsNotNone(app)

    async def test_j_user_call_consumer_handles_call_declined_and_ended_without_crash(self):
        # Test J: UserCallConsumer handles call_declined and call_ended events without ValueError missing handler
        from channels.testing import WebsocketCommunicator
        from apps.consultations.consumers import UserCallConsumer
        from channels.layers import get_channel_layer

        communicator = WebsocketCommunicator(UserCallConsumer.as_asgi(), "/ws/user-calls/")
        communicator.scope["user"] = self.midwife_user
        connected, _ = await communicator.connect()
        self.assertTrue(connected)

        channel_layer = get_channel_layer()

        # 1. Send canonical call_signal action=call_declined
        await channel_layer.group_send(f"user_calls_{self.midwife_user.id}", {
            "type": "call_signal",
            "action": "call_declined",
            "event": "call_declined",
            "call_id": "VOICE-DECLINE123",
            "consultation_id": str(self.consultation.id),
            "caller_id": str(self.patient.id),
        })
        res1 = await communicator.receive_json_from()
        self.assertEqual(res1["action"], "call_declined")

        # 2. Send direct type=call_declined event (defensive fallback test)
        await channel_layer.group_send(f"user_calls_{self.midwife_user.id}", {
            "type": "call_declined",
            "action": "call_declined",
            "event": "call_declined",
            "call_id": "VOICE-DECLINE456",
            "consultation_id": str(self.consultation.id),
            "caller_id": str(self.patient.id),
        })
        res2 = await communicator.receive_json_from()
        self.assertEqual(res2["action"], "call_declined")

        # 3. Send direct type=call_ended event (defensive fallback test)
        await channel_layer.group_send(f"user_calls_{self.midwife_user.id}", {
            "type": "call_ended",
            "action": "call_ended",
            "event": "call_ended",
            "call_id": "VOICE-END789",
            "consultation_id": str(self.consultation.id),
            "caller_id": str(self.patient.id),
        })
        res3 = await communicator.receive_json_from()
        self.assertEqual(res3["action"], "call_ended")

        await communicator.disconnect()



