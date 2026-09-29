import threading
from datetime import date, time, datetime, timedelta
from unittest.mock import patch
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase, APIClient
from django.contrib.auth import get_user_model
from django.db import connection

from apps.midwives.models import MidwifeProfile, Hospital
from apps.appointments.models import Availability, Appointment
from apps.notifications.models import Notification
from apps.appointments.tasks import send_automated_appointment_reminders

User = get_user_model()


class AppointmentManagementTestCase(APITestCase):

    def setUp(self):
        # Create Patient Users
        self.patient = User.objects.create_user(
            username="patient_apt",
            email="patient_apt@example.com",
            password="PatientPassword123!",
            role="PATIENT",
        )
        self.patient2 = User.objects.create_user(
            username="patient_apt2",
            email="patient_apt2@example.com",
            password="PatientPassword123!",
            role="PATIENT",
        )

        # Create Midwife User & Profile
        self.midwife_user = User.objects.create_user(
            username="midwife_apt",
            email="midwife_apt@example.com",
            password="MidwifePassword123!",
            role="MIDWIFE",
        )
        self.hospital = Hospital.objects.create(name="St. Mary Hospital", address="Addis Ababa")
        self.midwife_profile = MidwifeProfile.objects.create(
            user=self.midwife_user,
            hospital=self.hospital,
            license_number="MW-APT-100",
            verification_status="APPROVED",
            is_accepting_bookings=True,
            offered_consultation_types=["IN_PERSON", "VIRTUAL_VOICE"],
        )

        # Target future date for tests
        self.target_date = date.today() + timedelta(days=7)

        # Set Midwife Date-Specific Availability Period (09:00-10:00)
        self.availability = Availability.objects.create(
            midwife=self.midwife_profile,
            date=self.target_date,
            start_time="09:00:00",
            end_time="10:00:00",
            consultation_methods=["IN_PERSON", "VIRTUAL_VOICE"],
            is_active=True,
        )

    def test_availability_period_is_one_appointment(self):
        """09:00-10:00 creates exactly ONE bookable appointment period (not divided into sub-slots)."""
        url = reverse("slot-alias-list")
        res = self.client.get(url, {
            "midwife_id": str(self.midwife_profile.id),
            "date": self.target_date.strftime("%Y-%m-%d"),
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("slots", res.data)
        # MUST BE EXACTLY ONE PERIOD
        self.assertEqual(len(res.data["slots"]), 1)
        slot = res.data["slots"][0]
        self.assertEqual(slot["start_time"], "09:00")
        self.assertEqual(slot["end_time"], "10:00")
        self.assertEqual(slot["duration_minutes"], 60)

    def test_different_availability_durations(self):
        """Test that different start/end combinations work naturally as single periods."""
        test_date = date.today() + timedelta(days=8)
        # Create 5-minute, 15-minute, 20-minute, 30-minute availability periods on same date
        Availability.objects.create(midwife=self.midwife_profile, date=test_date, start_time="08:00:00", end_time="08:05:00", consultation_methods=["IN_PERSON"], is_active=True)
        Availability.objects.create(midwife=self.midwife_profile, date=test_date, start_time="08:10:00", end_time="08:25:00", consultation_methods=["IN_PERSON"], is_active=True)
        Availability.objects.create(midwife=self.midwife_profile, date=test_date, start_time="08:30:00", end_time="08:50:00", consultation_methods=["IN_PERSON"], is_active=True)
        Availability.objects.create(midwife=self.midwife_profile, date=test_date, start_time="09:00:00", end_time="09:30:00", consultation_methods=["IN_PERSON"], is_active=True)

        url = reverse("slot-alias-list")
        res = self.client.get(url, {
            "midwife_id": str(self.midwife_profile.id),
            "date": test_date.strftime("%Y-%m-%d"),
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        slots = res.data["slots"]
        self.assertEqual(len(slots), 4)
        self.assertEqual(slots[0]["duration_minutes"], 5)
        self.assertEqual(slots[1]["duration_minutes"], 15)
        self.assertEqual(slots[2]["duration_minutes"], 20)
        self.assertEqual(slots[3]["duration_minutes"], 30)

    def test_no_sub_slot_generation(self):
        """Explicitly verify 09:00-10:00 returns ONE 60-min period, NOT 09:00-09:30 & 09:30-10:00."""
        url = reverse("slot-alias-list")
        res = self.client.get(url, {
            "midwife_id": str(self.midwife_profile.id),
            "date": self.target_date.strftime("%Y-%m-%d"),
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        slots = res.data["slots"]
        self.assertEqual(len(slots), 1)
        self.assertNotEqual(len(slots), 2)
        self.assertEqual(slots[0]["start_time"], "09:00")
        self.assertEqual(slots[0]["end_time"], "10:00")

    def test_date_isolation(self):
        """Availability on Date A does not appear on Date B."""
        next_week = self.target_date + timedelta(days=7)
        url = reverse("slot-alias-list")
        res = self.client.get(url, {
            "midwife_id": str(self.midwife_profile.id),
            "date": next_week.strftime("%Y-%m-%d"),
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data["slots"]), 0)

    def test_multiple_periods_on_same_date(self):
        """Verify multiple separate availability periods on the same date."""
        Availability.objects.create(midwife=self.midwife_profile, date=self.target_date, start_time="14:00:00", end_time="15:30:00", consultation_methods=["VIRTUAL_VOICE"], is_active=True)
        Availability.objects.create(midwife=self.midwife_profile, date=self.target_date, start_time="17:00:00", end_time="18:00:00", consultation_methods=["VIRTUAL_VOICE"], is_active=True)

        url = reverse("slot-alias-list")
        res = self.client.get(url, {
            "midwife_id": str(self.midwife_profile.id),
            "date": self.target_date.strftime("%Y-%m-%d"),
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data["slots"]), 3)

    def test_consultation_methods_enforcement(self):
        """Verify consultation methods are enforced per availability period."""
        test_date = date.today() + timedelta(days=10)
        # Period 1: IN_PERSON only
        Availability.objects.create(midwife=self.midwife_profile, date=test_date, start_time="09:00:00", end_time="10:00:00", consultation_methods=["IN_PERSON"], is_active=True)
        # Period 2: VIRTUAL_VOICE only
        Availability.objects.create(midwife=self.midwife_profile, date=test_date, start_time="14:00:00", end_time="15:00:00", consultation_methods=["VIRTUAL_VOICE"], is_active=True)

        self.client.force_authenticate(user=self.patient)
        url = reverse("appointment-list")

        # Booking Period 1 with VIRTUAL_VOICE should fail
        res_fail = self.client.post(url, {
            "midwife": str(self.midwife_profile.id),
            "appointment_type": "VIRTUAL_VOICE",
            "scheduled_date": test_date.strftime("%Y-%m-%d"),
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        }, format="json")
        self.assertEqual(res_fail.status_code, status.HTTP_400_BAD_REQUEST)

        # Booking Period 1 with IN_PERSON should succeed
        res_pass = self.client.post(url, {
            "midwife": str(self.midwife_profile.id),
            "appointment_type": "IN_PERSON",
            "scheduled_date": test_date.strftime("%Y-%m-%d"),
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        }, format="json")
        self.assertEqual(res_pass.status_code, status.HTTP_201_CREATED)

    def test_create_availability_post_endpoint_regression(self):
        """Regression test: POST /api/v1/appointments/availability/ succeeds with valid date without HTTP 500 or AssertionError."""
        self.client.force_authenticate(user=self.midwife_user)
        url = reverse("availability-list")
        new_date = date.today() + timedelta(days=20)
        data = {
            "date": new_date.strftime("%Y-%m-%d"),
            "start_time": "14:00:00",
            "end_time": "16:00:00",
            "consultation_methods": ["IN_PERSON", "VIRTUAL_VOICE"],
            "is_active": True,
        }
        res = self.client.post(url, data, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["date"], new_date.strftime("%Y-%m-%d"))
        self.assertEqual(res.data["start_time"], "14:00:00")
        self.assertEqual(res.data["end_time"], "16:00:00")

    def test_booking_with_availability_id_and_field_aliases(self):
        """Regression test: POST /api/v1/appointments/ succeeds when passing availability_id or field aliases (midwife_id, date)."""
        self.client.force_authenticate(user=self.patient)
        url = reverse("appointment-list")

        # Booking using availability_id payload
        res = self.client.post(url, {
            "availability_id": str(self.availability.id),
            "appointment_type": "IN_PERSON",
            "reason": "Test booking via availability_id"
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["scheduled_date"], self.target_date.strftime("%Y-%m-%d"))
        self.assertEqual(res.data["start_time"], "09:00:00")
        self.assertEqual(res.data["end_time"], "10:00:00")

    def test_booking_validation_clear_error_messages(self):
        """Verifies HTTP 400 returns clear, field-specific validation error details."""
        self.client.force_authenticate(user=self.patient)
        url = reverse("appointment-list")

        # Booking on a date/time without active availability
        res = self.client.post(url, {
            "midwife": str(self.midwife_profile.id),
            "appointment_type": "IN_PERSON",
            "scheduled_date": (date.today() + timedelta(days=30)).strftime("%Y-%m-%d"),
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("start_time", res.data)
        self.assertIn("No active availability period found", res.data["start_time"][0])

    def test_inactive_availability_produces_no_slots(self):
        """Inactive availability cannot be booked and returns 0 slots."""
        self.availability.is_active = False
        self.availability.save()

        url = reverse("slot-alias-list")
        res = self.client.get(url, {
            "midwife_id": str(self.midwife_profile.id),
            "date": self.target_date.strftime("%Y-%m-%d"),
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(len(res.data["slots"]), 0)

    def test_double_booking_prevention(self):
        """PENDING and CONFIRMED appointments block the availability period."""
        # User A books 09:00-10:00
        self.client.force_authenticate(user=self.patient)
        url = reverse("appointment-list")
        res_a = self.client.post(url, {
            "midwife": str(self.midwife_profile.id),
            "appointment_type": "IN_PERSON",
            "scheduled_date": self.target_date.strftime("%Y-%m-%d"),
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        }, format="json")
        self.assertEqual(res_a.status_code, status.HTTP_201_CREATED)

        # User B attempts to book same 09:00-10:00
        self.client.force_authenticate(user=self.patient2)
        res_b = self.client.post(url, {
            "midwife": str(self.midwife_profile.id),
            "appointment_type": "IN_PERSON",
            "scheduled_date": self.target_date.strftime("%Y-%m-%d"),
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        }, format="json")
        self.assertEqual(res_b.status_code, status.HTTP_400_BAD_REQUEST)

    def test_concurrent_booking_safety(self):
        """Verify atomic transaction locking prevents double-booking the exact same availability period."""
        url = reverse("appointment-list")
        booking_data = {
            "midwife": str(self.midwife_profile.id),
            "appointment_type": "IN_PERSON",
            "scheduled_date": self.target_date.strftime("%Y-%m-%d"),
            "start_time": "09:00:00",
            "end_time": "10:00:00",
        }

        # Request A: Patient 1 books the 09:00-10:00 availability period
        self.client.force_authenticate(user=self.patient)
        res_a = self.client.post(url, booking_data, format="json")
        self.assertEqual(res_a.status_code, status.HTTP_201_CREATED)

        # Request B: Patient 2 attempts to book the exact same 09:00-10:00 availability period
        client2 = APIClient()
        client2.force_authenticate(user=self.patient2)
        res_b = client2.post(url, booking_data, format="json")
        self.assertEqual(res_b.status_code, status.HTTP_400_BAD_REQUEST)

        # Database contains exactly ONE appointment for this availability period
        apts = Appointment.objects.filter(
            midwife=self.midwife_profile,
            scheduled_date=self.target_date,
            start_time="09:00:00",
            end_time="10:00:00",
            status__in=[Appointment.AppointmentStatus.PENDING, Appointment.AppointmentStatus.CONFIRMED]
        )
        self.assertEqual(apts.count(), 1)

    def test_reschedule_and_cancel_actions(self):
        """Verify rescheduling to an available period works and cancelling frees the period."""
        # Create second availability period for rescheduling
        reschedule_date = date.today() + timedelta(days=15)
        Availability.objects.create(midwife=self.midwife_profile, date=reschedule_date, start_time="14:00:00", end_time="15:00:00", consultation_methods=["IN_PERSON"], is_active=True)

        apt = Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type="IN_PERSON",
            scheduled_date=self.target_date,
            start_time="09:00:00",
            end_time="10:00:00",
            status="CONFIRMED",
            created_by=self.patient,
        )

        # Reschedule to reschedule_date
        self.client.force_authenticate(user=self.patient)
        reschedule_url = reverse("appointment-reschedule", kwargs={"pk": apt.id})
        res = self.client.post(reschedule_url, {
            "scheduled_date": reschedule_date.strftime("%Y-%m-%d"),
            "start_time": "14:00:00",
            "end_time": "15:00:00",
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Cancel appointment
        cancel_url = reverse("appointment-cancel", kwargs={"pk": apt.id})
        cancel_res = self.client.post(cancel_url)
        self.assertEqual(cancel_res.status_code, status.HTTP_200_OK)
        self.assertEqual(cancel_res.data["status"], "CANCELLED")

    def test_midwife_confirm_action(self):
        apt = Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type="IN_PERSON",
            scheduled_date=self.target_date,
            start_time="09:00:00",
            end_time="10:00:00",
            status="PENDING",
            created_by=self.patient,
        )

        self.client.force_authenticate(user=self.midwife_user)
        confirm_url = reverse("appointment-confirm", kwargs={"pk": apt.id})
        res = self.client.post(confirm_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "CONFIRMED")

    def test_automated_celery_reminders_task(self):
        from django.utils import timezone
        tomorrow = (timezone.now() + timedelta(days=1)).date()
        Availability.objects.create(
            midwife=self.midwife_profile,
            date=tomorrow,
            start_time="10:00:00",
            end_time="11:00:00",
            consultation_methods=["VIRTUAL_VOICE"],
            is_active=True,
        )
        Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type="VIRTUAL_VOICE",
            scheduled_date=tomorrow,
            start_time="10:00:00",
            end_time="11:00:00",
            status="CONFIRMED",
            created_by=self.patient,
        )

        result_msg = send_automated_appointment_reminders()
        self.assertIn("Sent", result_msg)
        reminders = Notification.objects.filter(type="APPOINTMENT_REMINDER_24H")
        self.assertTrue(reminders.exists())

    def test_availability_creation_with_string_consultation_method_regression(self):
        """Regression test for screenshot issue: POSTing availability with string display names ('Voice call', 'In person') succeeds without 400."""
        self.client.force_authenticate(user=self.midwife_user)
        url = reverse("availability-list")
        test_d = date.today() + timedelta(days=25)

        # POST with single display string "Voice call"
        res = self.client.post(url, {
            "date": test_d.strftime("%Y-%m-%d"),
            "start_time": "11:00:00",
            "end_time": "12:00:00",
            "consultation_methods": "Voice call",
            "is_active": True,
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["consultation_methods"], ["VIRTUAL_VOICE"])

        # POST with list of display strings ["In person", "Voice call"]
        test_d2 = date.today() + timedelta(days=26)
        res2 = self.client.post(url, {
            "date": test_d2.strftime("%Y-%m-%d"),
            "start_time": "13:00:00",
            "end_time": "14:00:00",
            "consultation_methods": ["In person", "Voice call"],
            "is_active": True,
        }, format="json")
        self.assertEqual(res2.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res2.data["consultation_methods"], ["IN_PERSON", "VIRTUAL_VOICE"])

    def test_booking_with_empty_availability_methods_fallback_regression(self):
        """Regression test for POST /api/v1/appointments/ HTTP 400 issue: Availability with empty consultation_methods uses fallback and permits booking."""
        empty_avail_date = date.today() + timedelta(days=28)
        # Create availability period with empty consultation_methods []
        avail = Availability.objects.create(
            midwife=self.midwife_profile,
            date=empty_avail_date,
            start_time="10:00:00",
            end_time="11:00:00",
            consultation_methods=[],
            is_active=True,
        )

        self.client.force_authenticate(user=self.patient)
        url = reverse("appointment-list")

        # Booking VIRTUAL_VOICE should succeed via fallback instead of returning HTTP 400
        res = self.client.post(url, {
            "availability_id": str(avail.id),
            "type": "Voice call",
            "reason": "Routine Checkup"
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["appointment_type"], "VIRTUAL_VOICE")
        self.assertEqual(res.data["scheduled_date"], empty_avail_date.strftime("%Y-%m-%d"))


class AvailabilitySchedulingValidationTestCase(APITestCase):

    def setUp(self):
        self.midwife_user = User.objects.create_user(
            username="midwife_sched",
            email="midwife_sched@example.com",
            password="MidwifePassword123!",
            role="MIDWIFE",
        )
        self.hospital = Hospital.objects.create(name="Central Hospital", address="Addis Ababa")
        self.midwife_profile = MidwifeProfile.objects.create(
            user=self.midwife_user,
            hospital=self.hospital,
            license_number="MW-SCHED-100",
            verification_status="APPROVED",
            offered_consultation_types=["IN_PERSON", "VIRTUAL_VOICE"],
        )
        self.client.force_authenticate(user=self.midwife_user)
        self.url = reverse("availability-list")

        self.fixed_today = date(2026, 9, 15)
        self.fixed_now_datetime = datetime(2026, 9, 15, 14, 0, 0, tzinfo=timezone.get_current_timezone())

    @patch("django.utils.timezone.localdate")
    @patch("django.utils.timezone.localtime")
    def test_yesterday_rejected(self, mock_localtime, mock_localdate):
        """1. yesterday -> rejected"""
        mock_localdate.return_value = self.fixed_today
        mock_localtime.return_value = self.fixed_now_datetime

        yesterday = self.fixed_today - timedelta(days=1)
        res = self.client.post(self.url, {
            "date": yesterday.strftime("%Y-%m-%d"),
            "start_time": "15:00:00",
            "end_time": "16:00:00",
            "consultation_methods": ["IN_PERSON"],
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date", res.data)

    @patch("django.utils.timezone.localdate")
    @patch("django.utils.timezone.localtime")
    def test_today_past_start_time_rejected(self, mock_localtime, mock_localdate):
        """2. today with a past start time -> rejected"""
        mock_localdate.return_value = self.fixed_today
        mock_localtime.return_value = self.fixed_now_datetime

        res = self.client.post(self.url, {
            "date": self.fixed_today.strftime("%Y-%m-%d"),
            "start_time": "13:30:00",
            "end_time": "14:30:00",
            "consultation_methods": ["IN_PERSON"],
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("start_time", res.data)

    @patch("django.utils.timezone.localdate")
    @patch("django.utils.timezone.localtime")
    def test_today_equal_start_time_rejected(self, mock_localtime, mock_localdate):
        """3. today with start time equal to current time -> rejected"""
        mock_localdate.return_value = self.fixed_today
        mock_localtime.return_value = self.fixed_now_datetime

        res = self.client.post(self.url, {
            "date": self.fixed_today.strftime("%Y-%m-%d"),
            "start_time": "14:00:00",
            "end_time": "15:00:00",
            "consultation_methods": ["IN_PERSON"],
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("start_time", res.data)

    @patch("django.utils.timezone.localdate")
    @patch("django.utils.timezone.localtime")
    def test_today_future_start_time_accepted(self, mock_localtime, mock_localdate):
        """4. today with a future start time -> accepted"""
        mock_localdate.return_value = self.fixed_today
        mock_localtime.return_value = self.fixed_now_datetime

        res = self.client.post(self.url, {
            "date": self.fixed_today.strftime("%Y-%m-%d"),
            "start_time": "14:30:00",
            "end_time": "15:30:00",
            "consultation_methods": ["IN_PERSON"],
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    @patch("django.utils.timezone.localdate")
    @patch("django.utils.timezone.localtime")
    def test_tomorrow_future_date_accepted(self, mock_localtime, mock_localdate):
        """5. tomorrow/future date -> accepted"""
        mock_localdate.return_value = self.fixed_today
        mock_localtime.return_value = self.fixed_now_datetime

        tomorrow = self.fixed_today + timedelta(days=1)
        res = self.client.post(self.url, {
            "date": tomorrow.strftime("%Y-%m-%d"),
            "start_time": "09:00:00",
            "end_time": "10:00:00",
            "consultation_methods": ["IN_PERSON"],
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)

    @patch("django.utils.timezone.localdate")
    @patch("django.utils.timezone.localtime")
    def test_end_time_before_or_equal_start_time_rejected(self, mock_localtime, mock_localdate):
        """6. end_time <= start_time -> rejected"""
        mock_localdate.return_value = self.fixed_today
        mock_localtime.return_value = self.fixed_now_datetime

        tomorrow = self.fixed_today + timedelta(days=1)
        res_a = self.client.post(self.url, {
            "date": tomorrow.strftime("%Y-%m-%d"),
            "start_time": "10:00:00",
            "end_time": "09:00:00",
            "consultation_methods": ["IN_PERSON"],
        }, format="json")
        self.assertEqual(res_a.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("start_time", res_a.data)

        res_b = self.client.post(self.url, {
            "date": tomorrow.strftime("%Y-%m-%d"),
            "start_time": "10:00:00",
            "end_time": "10:00:00",
            "consultation_methods": ["IN_PERSON"],
        }, format="json")
        self.assertEqual(res_b.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("start_time", res_b.data)

    @patch("django.utils.timezone.localdate")
    @patch("django.utils.timezone.localtime")
    def test_update_existing_availability_to_past_rejected(self, mock_localtime, mock_localdate):
        """7. updating an existing availability to a past date/time -> rejected"""
        mock_localdate.return_value = self.fixed_today
        mock_localtime.return_value = self.fixed_now_datetime

        tomorrow = self.fixed_today + timedelta(days=1)
        avail = Availability.objects.create(
            midwife=self.midwife_profile,
            date=tomorrow,
            start_time=time(10, 0),
            end_time=time(11, 0),
            consultation_methods=["IN_PERSON"],
            is_active=True,
        )

        detail_url = reverse("availability-detail", kwargs={"pk": avail.id})

        yesterday = self.fixed_today - timedelta(days=1)
        res_date = self.client.patch(detail_url, {"date": yesterday.strftime("%Y-%m-%d")}, format="json")
        self.assertEqual(res_date.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("date", res_date.data)

        res_time = self.client.patch(detail_url, {"date": self.fixed_today.strftime("%Y-%m-%d")}, format="json")
        self.assertEqual(res_time.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("start_time", res_time.data)

