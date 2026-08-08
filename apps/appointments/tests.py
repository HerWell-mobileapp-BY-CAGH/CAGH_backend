from datetime import date, timedelta
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from apps.midwives.models import MidwifeProfile, Hospital, BlockedDate
from apps.appointments.models import Availability, TimeSlot, Appointment
from apps.notifications.models import Notification
from apps.appointments.tasks import send_automated_appointment_reminders

User = get_user_model()


class AppointmentManagementTestCase(APITestCase):

    def setUp(self):
        # Create Patient User
        self.patient = User.objects.create_user(
            username="patient_apt",
            email="patient_apt@example.com",
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
            offered_consultation_types=["IN_PERSON", "VIRTUAL_VOICE"],
        )

        # Set Midwife Availability (Monday = 0)
        self.availability = Availability.objects.create(
            midwife=self.midwife_profile,
            day_of_week=0,
            start_time="09:00:00",
            end_time="12:00:00",
            is_active=True,
        )

        # Future Monday date
        today = date.today()
        days_ahead = 0 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        self.target_monday = today + timedelta(days=days_ahead)

    def test_appointment_booking_and_dual_notifications(self):
        self.client.force_authenticate(user=self.patient)
        url = reverse("appointment-list")
        data = {
            "midwife": str(self.midwife_profile.id),
            "appointment_type": "IN_PERSON",
            "scheduled_date": self.target_monday.strftime("%Y-%m-%d"),
            "start_time": "09:00:00",
            "end_time": "09:30:00",
            "reason": "Routine maternal checkup",
        }
        res = self.client.post(url, data, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertIn("appointment_number", res.data)
        self.assertEqual(res.data["status"], "PENDING")

        # Verify Dual-side Notifications
        patient_notifs = Notification.objects.filter(user=self.patient)
        midwife_notifs = Notification.objects.filter(user=self.midwife_user)
        self.assertTrue(patient_notifs.exists())
        self.assertTrue(midwife_notifs.exists())

    def test_double_booking_prevention(self):
        # Create existing appointment
        Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type="VIRTUAL_VOICE",
            scheduled_date=self.target_monday,
            start_time="09:00:00",
            end_time="09:30:00",
            status="CONFIRMED",
            created_by=self.patient,
        )

        # Try booking overlapping time slot
        self.client.force_authenticate(user=self.patient)
        url = reverse("appointment-list")
        data = {
            "midwife": str(self.midwife_profile.id),
            "appointment_type": "IN_PERSON",
            "scheduled_date": self.target_monday.strftime("%Y-%m-%d"),
            "start_time": "09:15:00",
            "end_time": "09:45:00",
        }
        res = self.client.post(url, data, format="json")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_time_slots_availability_generator(self):
        url = reverse("slot-alias-list")
        res = self.client.get(url, {
            "midwife_id": str(self.midwife_profile.id),
            "date": self.target_monday.strftime("%Y-%m-%d"),
        })
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertIn("slots", res.data)
        self.assertGreater(len(res.data["slots"]), 0)

    def test_reschedule_and_cancel_actions(self):
        apt = Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type="IN_PERSON",
            scheduled_date=self.target_monday,
            start_time="10:00:00",
            end_time="10:30:00",
            status="CONFIRMED",
            created_by=self.patient,
        )

        # Reschedule
        self.client.force_authenticate(user=self.patient)
        reschedule_url = reverse("appointment-reschedule", kwargs={"pk": apt.id})
        res = self.client.post(reschedule_url, {
            "scheduled_date": self.target_monday.strftime("%Y-%m-%d"),
            "start_time": "11:00:00",
            "end_time": "11:30:00",
        }, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)

        # Cancel
        cancel_url = reverse("appointment-cancel", kwargs={"pk": apt.id})
        cancel_res = self.client.post(cancel_url)
        self.assertEqual(cancel_res.status_code, status.HTTP_200_OK)
        self.assertEqual(cancel_res.data["status"], "CANCELLED")

    def test_midwife_confirm_action(self):
        apt = Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type="IN_PERSON",
            scheduled_date=self.target_monday,
            start_time="11:30:00",
            end_time="12:00:00",
            status="PENDING",
            created_by=self.patient,
        )

        self.client.force_authenticate(user=self.midwife_user)
        confirm_url = reverse("appointment-confirm", kwargs={"pk": apt.id})
        res = self.client.post(confirm_url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["status"], "CONFIRMED")

    def test_automated_celery_reminders_task(self):
        # Create appointment for tomorrow
        from django.utils import timezone
        tomorrow = (timezone.now() + timedelta(days=1)).date()
        Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type="VIRTUAL_VOICE",
            scheduled_date=tomorrow,
            start_time="10:00:00",
            end_time="10:30:00",
            status="CONFIRMED",
            created_by=self.patient,
        )

        result_msg = send_automated_appointment_reminders()
        self.assertIn("Sent", result_msg)
        reminders = Notification.objects.filter(type="APPOINTMENT_REMINDER_24H")
        self.assertTrue(reminders.exists())
