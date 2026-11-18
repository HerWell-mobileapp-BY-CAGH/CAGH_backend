from datetime import date, timedelta
from django.urls import reverse
from rest_framework import status
from django.utils import timezone
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from apps.midwives.models import MidwifeProfile, Hospital
from apps.appointments.models import Appointment
from apps.consultations.models import Consultation, ConsultationNote, VideoSession
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

    def test_consultation_completion_lifecycle(self):
        consultation = Consultation.objects.create(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="VIRTUAL_VOICE",
            status="ACTIVE",
        )

        self.client.force_authenticate(user=self.midwife_user)
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

        notification = Notification.objects.filter(user=self.patient, action="CONSULTATION_COMPLETED").first()
        self.assertIsNotNone(notification)

    def test_unauthorized_user_cannot_access_consultation_call_midwife(self):
        consultation = Consultation.objects.create(
            appointment=self.confirmed_appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="VIRTUAL_VOICE",
            status="SCHEDULED",
        )

        # Unassigned midwife attempts to fetch call midwife details (Permission test)
        self.client.force_authenticate(user=self.other_midwife_user)
        call_url = reverse("consultation-call-midwife", kwargs={"pk": consultation.id})
        res_bad = self.client.get(call_url)
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
