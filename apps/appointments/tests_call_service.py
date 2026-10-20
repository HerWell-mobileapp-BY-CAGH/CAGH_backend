from datetime import date, time, datetime, timedelta
from unittest.mock import patch
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from apps.common.phone_utils import (
    normalize_ethiopian_phone,
    format_tel_uri,
    ETHIO_TELECOM_CARRIER,
    SAFARICOM_CARRIER,
)
from apps.appointments.models import Appointment, Availability
from apps.appointments.call_service import AppointmentCallService, EAT_TIMEZONE
from apps.midwives.models import MidwifeProfile, Hospital
from apps.consultations.models import Consultation

User = get_user_model()


class EthiopianPhoneNormalizationTestCase(APITestCase):
    """
    Unit tests for Ethiopian mobile phone number normalization, validation,
    RFC 3966 tel: URI generation, and carrier detection.
    """

    def test_ethio_telecom_local_format(self):
        result = normalize_ethiopian_phone("0911223344")
        self.assertTrue(result["is_valid"])
        self.assertTrue(result["is_mobile"])
        self.assertEqual(result["carrier"], ETHIO_TELECOM_CARRIER)
        self.assertEqual(result["phone_number"], "+251911223344")
        self.assertEqual(result["phone_number_local"], "0911223344")
        self.assertEqual(result["tel_uri"], "tel:+251911223344")
        self.assertIsNone(result["error"])

    def test_ethio_telecom_international_format(self):
        result = normalize_ethiopian_phone("+251911223344")
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["carrier"], ETHIO_TELECOM_CARRIER)
        self.assertEqual(result["phone_number"], "+251911223344")
        self.assertEqual(result["phone_number_local"], "0911223344")
        self.assertEqual(result["tel_uri"], "tel:+251911223344")

    def test_ethio_telecom_alternative_prefixes(self):
        # 00251 prefix
        res_00 = normalize_ethiopian_phone("00251911223344")
        self.assertTrue(res_00["is_valid"])
        self.assertEqual(res_00["phone_number"], "+251911223344")
        self.assertEqual(res_00["carrier"], ETHIO_TELECOM_CARRIER)

        # 251 without plus
        res_no_plus = normalize_ethiopian_phone("251911223344")
        self.assertTrue(res_no_plus["is_valid"])
        self.assertEqual(res_no_plus["phone_number"], "+251911223344")
        self.assertEqual(res_no_plus["carrier"], ETHIO_TELECOM_CARRIER)

        # 9 digits directly
        res_9 = normalize_ethiopian_phone("911223344")
        self.assertTrue(res_9["is_valid"])
        self.assertEqual(res_9["phone_number"], "+251911223344")
        self.assertEqual(res_9["carrier"], ETHIO_TELECOM_CARRIER)

    def test_safaricom_ethiopia_local_format(self):
        result = normalize_ethiopian_phone("0712345678")
        self.assertTrue(result["is_valid"])
        self.assertTrue(result["is_mobile"])
        self.assertEqual(result["carrier"], SAFARICOM_CARRIER)
        self.assertEqual(result["phone_number"], "+251712345678")
        self.assertEqual(result["phone_number_local"], "0712345678")
        self.assertEqual(result["tel_uri"], "tel:+251712345678")
        self.assertIsNone(result["error"])

    def test_safaricom_ethiopia_international_format(self):
        result = normalize_ethiopian_phone("+251712345678")
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["carrier"], SAFARICOM_CARRIER)
        self.assertEqual(result["phone_number"], "+251712345678")
        self.assertEqual(result["phone_number_local"], "0712345678")
        self.assertEqual(result["tel_uri"], "tel:+251712345678")

    def test_safaricom_ethiopia_alternative_prefixes(self):
        # 00251 prefix
        res_00 = normalize_ethiopian_phone("00251712345678")
        self.assertTrue(res_00["is_valid"])
        self.assertEqual(res_00["phone_number"], "+251712345678")
        self.assertEqual(res_00["carrier"], SAFARICOM_CARRIER)

        # 251 without plus
        res_no_plus = normalize_ethiopian_phone("251712345678")
        self.assertTrue(res_no_plus["is_valid"])
        self.assertEqual(res_no_plus["phone_number"], "+251712345678")
        self.assertEqual(res_no_plus["carrier"], SAFARICOM_CARRIER)

        # 9 digits directly
        res_7 = normalize_ethiopian_phone("712345678")
        self.assertTrue(res_7["is_valid"])
        self.assertEqual(res_7["phone_number"], "+251712345678")
        self.assertEqual(res_7["carrier"], SAFARICOM_CARRIER)

    def test_number_formatting_with_noise(self):
        # Spaces, hyphens, brackets, dots
        res_spaced = normalize_ethiopian_phone("09 11 22 33 44")
        self.assertTrue(res_spaced["is_valid"])
        self.assertEqual(res_spaced["phone_number"], "+251911223344")

        res_hyphen = normalize_ethiopian_phone("+251-7-12-34-56-78")
        self.assertTrue(res_hyphen["is_valid"])
        self.assertEqual(res_hyphen["phone_number"], "+251712345678")

        res_brackets = normalize_ethiopian_phone("(0911) 22-33-44")
        self.assertTrue(res_brackets["is_valid"])
        self.assertEqual(res_brackets["phone_number"], "+251911223344")

        res_dots = normalize_ethiopian_phone("+251.91.122.3344")
        self.assertTrue(res_dots["is_valid"])
        self.assertEqual(res_dots["phone_number"], "+251911223344")

    def test_format_tel_uri_helper(self):
        self.assertEqual(format_tel_uri("0911223344"), "tel:+251911223344")
        self.assertEqual(format_tel_uri("+251712345678"), "tel:+251712345678")
        self.assertIsNone(format_tel_uri("invalid_phone"))
        self.assertIsNone(format_tel_uri(None))

    def test_invalid_and_edge_case_numbers(self):
        # Missing / Empty / None
        self.assertFalse(normalize_ethiopian_phone(None)["is_valid"])
        self.assertFalse(normalize_ethiopian_phone("")["is_valid"])
        self.assertFalse(normalize_ethiopian_phone("   ")["is_valid"])

        # Non-Ethiopian country code (+1, +44, +233)
        res_us = normalize_ethiopian_phone("+14155552671")
        self.assertFalse(res_us["is_valid"])
        self.assertIn("country code", res_us["error"].lower())

        res_gh = normalize_ethiopian_phone("+233501234567")
        self.assertFalse(res_gh["is_valid"])

        # Ethiopian fixed line (011...) - correctly rejected for mobile SIM calling
        res_landline = normalize_ethiopian_phone("0111223344")
        self.assertFalse(res_landline["is_valid"])
        self.assertIn("landline", res_landline["error"].lower())

        # Invalid prefixes
        res_prefix = normalize_ethiopian_phone("0811223344")
        self.assertFalse(res_prefix["is_valid"])
        self.assertIn("08", res_prefix["error"])

        # Too short / too long
        self.assertFalse(normalize_ethiopian_phone("091122")["is_valid"])
        self.assertFalse(normalize_ethiopian_phone("+25191122334455")["is_valid"])


class AppointmentCallServiceTestCase(APITestCase):
    """
    Unit and integration tests for AppointmentCallService, EAT call window calculations,
    appointment status checks, ownership verification, and secure phone disclosure.
    """

    def setUp(self):
        self.patient = User.objects.create_user(
            username="patient_call_user",
            email="pat_call@example.com",
            password="Password123!",
            role="PATIENT",
            phone_number="+251922334455"
        )
        self.other_patient = User.objects.create_user(
            username="unauthorized_patient",
            email="unauth@example.com",
            password="Password123!",
            role="PATIENT",
            phone_number="+251933445566"
        )
        self.midwife_user = User.objects.create_user(
            username="midwife_call_user",
            email="mw_call@example.com",
            password="Password123!",
            role="MIDWIFE",
            phone_number="+251911223344"  # Ethio Telecom
        )
        self.hospital = Hospital.objects.create(name="Central Clinic", address="Addis Ababa")
        self.midwife_profile = MidwifeProfile.objects.create(
            user=self.midwife_user,
            hospital=self.hospital,
            license_number="MW-CALL-101",
            verification_status="APPROVED",
            offered_consultation_types=["IN_PERSON", "VIRTUAL_VOICE"]
        )
        self.admin_user = User.objects.create_superuser(
            username="admin_call_user",
            email="admin_call@example.com",
            password="Password123!"
        )

        # Standard appointment date and window
        self.test_date = date(2026, 10, 19)
        self.start_time = time(14, 0)   # 2:00 PM EAT
        self.end_time = time(14, 30)    # 2:30 PM EAT

        self.appointment = Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type=Appointment.AppointmentType.VIRTUAL_VOICE,
            status=Appointment.AppointmentStatus.CONFIRMED,
            scheduled_date=self.test_date,
            start_time=self.start_time,
            end_time=self.end_time,
            created_by=self.patient,
        )

    def test_call_eligibility_active_window_ethio_telecom(self):
        # Time within window: 2:15 PM EAT
        mock_now = datetime(2026, 10, 19, 14, 15, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            eligibility = AppointmentCallService.check_call_eligibility(self.appointment, self.patient)

            self.assertTrue(eligibility["can_call"])
            self.assertTrue(eligibility["is_call_window_active"])
            self.assertEqual(eligibility["window_state"], "ACTIVE_WINDOW")
            self.assertEqual(eligibility["phone_number"], "+251911223344")
            self.assertEqual(eligibility["phone_number_local"], "0911223344")
            self.assertEqual(eligibility["tel_uri"], "tel:+251911223344")
            self.assertEqual(eligibility["carrier"], ETHIO_TELECOM_CARRIER)
            self.assertIsNone(eligibility["reason"])
            self.assertIn("Call window is active", eligibility["message"])

    def test_call_eligibility_active_window_safaricom_ethiopia(self):
        # Update midwife to Safaricom Ethiopia mobile number (07...)
        self.midwife_user.phone_number = "0712345678"
        self.midwife_user.save()

        mock_now = datetime(2026, 10, 19, 14, 10, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            eligibility = AppointmentCallService.check_call_eligibility(self.appointment, self.patient)

            self.assertTrue(eligibility["can_call"])
            self.assertTrue(eligibility["is_call_window_active"])
            self.assertEqual(eligibility["window_state"], "ACTIVE_WINDOW")
            self.assertEqual(eligibility["phone_number"], "+251712345678")
            self.assertEqual(eligibility["tel_uri"], "tel:+251712345678")
            self.assertEqual(eligibility["carrier"], SAFARICOM_CARRIER)

    def test_call_eligibility_before_window_masks_phone_number(self):
        # Before window: 1:30 PM EAT (30 minutes before 2:00 PM)
        mock_now = datetime(2026, 10, 19, 13, 30, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            eligibility = AppointmentCallService.check_call_eligibility(self.appointment, self.patient)

            self.assertFalse(eligibility["can_call"])
            self.assertFalse(eligibility["is_call_window_active"])
            self.assertEqual(eligibility["window_state"], "BEFORE_WINDOW")
            # Phone number and tel: URI MUST be masked (None) for privacy
            self.assertIsNone(eligibility["phone_number"])
            self.assertIsNone(eligibility["phone_number_local"])
            self.assertIsNone(eligibility["tel_uri"])
            self.assertEqual(eligibility["seconds_until_window"], 1800)
            self.assertIn("enabled during your scheduled window", eligibility["message"])

    def test_call_eligibility_expired_window_masks_phone_number(self):
        # After window: 2:45 PM EAT (15 minutes after 2:30 PM)
        mock_now = datetime(2026, 10, 19, 14, 45, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            eligibility = AppointmentCallService.check_call_eligibility(self.appointment, self.patient)

            self.assertFalse(eligibility["can_call"])
            self.assertFalse(eligibility["is_call_window_active"])
            self.assertEqual(eligibility["window_state"], "EXPIRED_WINDOW")
            self.assertIsNone(eligibility["phone_number"])
            self.assertIsNone(eligibility["tel_uri"])
            self.assertIn("window ended", eligibility["message"])

    def test_call_eligibility_cancelled_appointment(self):
        self.appointment.status = Appointment.AppointmentStatus.CANCELLED
        self.appointment.save()

        mock_now = datetime(2026, 10, 19, 14, 15, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            eligibility = AppointmentCallService.check_call_eligibility(self.appointment, self.patient)

            self.assertFalse(eligibility["can_call"])
            self.assertIsNone(eligibility["phone_number"])
            self.assertIsNone(eligibility["tel_uri"])
            self.assertIn("cancelled", eligibility["reason"].lower())

    def test_call_eligibility_pending_appointment(self):
        self.appointment.status = Appointment.AppointmentStatus.PENDING
        self.appointment.save()

        mock_now = datetime(2026, 10, 19, 14, 15, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            eligibility = AppointmentCallService.check_call_eligibility(self.appointment, self.patient)

            self.assertFalse(eligibility["can_call"])
            self.assertIsNone(eligibility["phone_number"])
            self.assertIn("pending", eligibility["reason"].lower())

    def test_call_eligibility_missing_midwife_phone(self):
        self.midwife_user.phone_number = None
        self.midwife_user.save()

        mock_now = datetime(2026, 10, 19, 14, 15, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            eligibility = AppointmentCallService.check_call_eligibility(self.appointment, self.patient)

            self.assertFalse(eligibility["can_call"])
            self.assertIsNone(eligibility["phone_number"])
            self.assertIsNone(eligibility["tel_uri"])
            self.assertIn("not registered a contact phone number", eligibility["reason"])

    def test_call_eligibility_invalid_midwife_phone(self):
        self.midwife_user.phone_number = "12345"
        self.midwife_user.save()

        mock_now = datetime(2026, 10, 19, 14, 15, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            eligibility = AppointmentCallService.check_call_eligibility(self.appointment, self.patient)

            self.assertFalse(eligibility["can_call"])
            self.assertIsNone(eligibility["phone_number"])
            self.assertIn("invalid", eligibility["reason"].lower())

    def test_call_eligibility_unauthorized_user(self):
        mock_now = datetime(2026, 10, 19, 14, 15, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            eligibility = AppointmentCallService.check_call_eligibility(self.appointment, self.other_patient)

            self.assertFalse(eligibility["can_call"])
            self.assertFalse(eligibility["is_authorized"])
            self.assertIsNone(eligibility["phone_number"])
            self.assertIn("permission", eligibility["reason"].lower())


class AppointmentCallApiEndpointsTestCase(APITestCase):
    """
    API integration tests for /api/v1/appointments/{id}/call-midwife/ endpoint,
    serializer integration, and consultation endpoints.
    """

    def setUp(self):
        self.patient = User.objects.create_user(
            username="patient_api_call",
            email="pat_api@example.com",
            password="Password123!",
            role="PATIENT",
            phone_number="+251911000001"
        )
        self.other_patient = User.objects.create_user(
            username="other_api_patient",
            email="other_api@example.com",
            password="Password123!",
            role="PATIENT",
            phone_number="+251911000002"
        )
        self.midwife_user = User.objects.create_user(
            username="midwife_api_call",
            email="mw_api@example.com",
            password="Password123!",
            role="MIDWIFE",
            phone_number="+251911223344"
        )
        self.hospital = Hospital.objects.create(name="St. Paul Hospital", address="Addis Ababa")
        self.midwife_profile = MidwifeProfile.objects.create(
            user=self.midwife_user,
            hospital=self.hospital,
            license_number="MW-API-202",
            verification_status="APPROVED",
            offered_consultation_types=["IN_PERSON", "VIRTUAL_VOICE"]
        )

        self.appointment = Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type=Appointment.AppointmentType.VIRTUAL_VOICE,
            status=Appointment.AppointmentStatus.CONFIRMED,
            scheduled_date=date(2026, 10, 19),
            start_time=time(14, 0),
            end_time=time(14, 30),
            created_by=self.patient,
        )

        self.consultation = Consultation.objects.create(
            appointment=self.appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type=Consultation.ConsultationType.VIRTUAL_VOICE,
            status=Consultation.ConsultationStatus.SCHEDULED,
        )

        self.url = f"/api/v1/appointments/{self.appointment.id}/call-midwife/"
        self.consult_url = f"/api/v1/consultations/{self.consultation.id}/call-midwife/"

    def test_get_call_midwife_during_active_window(self):
        self.client.force_authenticate(user=self.patient)
        mock_now = datetime(2026, 10, 19, 14, 15, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            res = self.client.get(self.url)
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertTrue(res.data["can_call"])
            self.assertTrue(res.data["is_call_window_active"])
            self.assertEqual(res.data["window_state"], "ACTIVE_WINDOW")
            self.assertEqual(res.data["tel_uri"], "tel:+251911223344")
            self.assertEqual(res.data["phone_number"], "+251911223344")
            self.assertEqual(res.data["carrier"], ETHIO_TELECOM_CARRIER)

    def test_get_call_midwife_before_window_returns_200_with_can_call_false(self):
        self.client.force_authenticate(user=self.patient)
        mock_now = datetime(2026, 10, 19, 12, 0, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            res = self.client.get(self.url)
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertFalse(res.data["can_call"])
            self.assertFalse(res.data["is_call_window_active"])
            self.assertEqual(res.data["window_state"], "BEFORE_WINDOW")
            # phone_number and tel_uri must not be disclosed
            self.assertIsNone(res.data["phone_number"])
            self.assertIsNone(res.data["tel_uri"])
            self.assertIn("enabled during your scheduled window", res.data["message"])

    def test_post_call_midwife_during_active_window_succeeds(self):
        self.client.force_authenticate(user=self.patient)
        mock_now = datetime(2026, 10, 19, 14, 15, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            res = self.client.post(self.url)
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertTrue(res.data["can_call"])
            self.assertEqual(res.data["tel_uri"], "tel:+251911223344")

    def test_post_call_midwife_outside_window_returns_400(self):
        self.client.force_authenticate(user=self.patient)
        mock_now = datetime(2026, 10, 19, 11, 0, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            res = self.client.post(self.url)
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertFalse(res.data["can_call"])
            self.assertIsNone(res.data["phone_number"])
            self.assertIsNone(res.data["tel_uri"])

    def test_post_call_midwife_cancelled_returns_400(self):
        self.appointment.status = Appointment.AppointmentStatus.CANCELLED
        self.appointment.save()

        self.client.force_authenticate(user=self.patient)
        mock_now = datetime(2026, 10, 19, 14, 15, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            res = self.client.post(self.url)
            self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
            self.assertFalse(res.data["can_call"])
            self.assertIn("cancelled", res.data["reason"].lower())

    def test_unauthorized_user_forbidden(self):
        self.client.force_authenticate(user=self.other_patient)
        res_get = self.client.get(self.url)
        self.assertEqual(res_get.status_code, status.HTTP_403_FORBIDDEN)

        res_post = self.client.post(self.url)
        self.assertEqual(res_post.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_request_unauthorized(self):
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_endpoint_aliases_work(self):
        self.client.force_authenticate(user=self.patient)
        mock_now = datetime(2026, 10, 19, 14, 15, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            # snake_case alias
            res_snake = self.client.get(f"/api/v1/appointments/{self.appointment.id}/call_midwife/")
            self.assertEqual(res_snake.status_code, status.HTTP_200_OK)
            self.assertTrue(res_snake.data["can_call"])

            # call-access alias
            res_access = self.client.get(f"/api/v1/appointments/{self.appointment.id}/call-access/")
            self.assertEqual(res_access.status_code, status.HTTP_200_OK)
            self.assertTrue(res_access.data["can_call"])

            # call-eligibility alias
            res_eligibility = self.client.get(f"/api/v1/appointments/{self.appointment.id}/call-eligibility/")
            self.assertEqual(res_eligibility.status_code, status.HTTP_200_OK)
            self.assertTrue(res_eligibility.data["can_call"])

    def test_appointment_serializer_includes_call_eligibility(self):
        self.client.force_authenticate(user=self.patient)
        mock_now = datetime(2026, 10, 19, 14, 15, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            detail_url = f"/api/v1/appointments/{self.appointment.id}/"
            res = self.client.get(detail_url)
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertIn("call_eligibility", res.data)
            self.assertIsNotNone(res.data["call_eligibility"])
            self.assertTrue(res.data["call_eligibility"]["can_call"])
            self.assertEqual(res.data["call_eligibility"]["tel_uri"], "tel:+251911223344")

    def test_consultation_call_midwife_endpoint(self):
        self.client.force_authenticate(user=self.patient)
        mock_now = datetime(2026, 10, 19, 14, 15, 0, tzinfo=EAT_TIMEZONE)

        with patch("apps.appointments.call_service.AppointmentCallService.get_eat_now", return_value=mock_now):
            res = self.client.get(self.consult_url)
            self.assertEqual(res.status_code, status.HTTP_200_OK)
            self.assertTrue(res.data["can_call"])
            self.assertEqual(res.data["tel_uri"], "tel:+251911223344")
            self.assertEqual(res.data["carrier"], ETHIO_TELECOM_CARRIER)
