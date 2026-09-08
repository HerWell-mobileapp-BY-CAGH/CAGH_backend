from django.urls import reverse
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from apps.users.models import Profile
from apps.common.models import Facility
from apps.notifications.models import Notification
from apps.users.models import EmergencyContact


User = get_user_model()


class LanguageSelectionTestCase(APITestCase):

    def test_list_supported_languages(self):
        url = reverse("language-list")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["default_language"], "en")
        codes = [lang["code"] for lang in response.data["supported_languages"]]
        self.assertIn("en", codes)
        self.assertIn("am", codes)

    def test_select_amharic_language_unauthenticated(self):
        url = reverse("language-select")
        data = {"language": "am"}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["language"], "am")
        self.assertEqual(response.data["name"], "Amharic")
        self.assertEqual(response.data["native_name"], "አማርኛ")

    def test_select_language_authenticated_user(self):
        user = User.objects.create_user(
            username="lang_user",
            email="lang@example.com",
            password="Password123!",
        )
        Profile.objects.create(user=user, first_name="Test", last_name="User")
        self.client.force_authenticate(user=user)

        url = reverse("language-select")
        data = {"language": "am"}
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        user.profile.refresh_from_db()
        self.assertEqual(user.profile.preferred_language, "am")

    def test_amharic_locale_translation(self):
        from django.utils.translation import gettext as _
        from django.utils.translation import activate, deactivate
        activate('am')
        self.assertEqual(_('Patient'), 'ታካሚ')
        self.assertEqual(_('Midwife'), 'አላዋቂ / መላዋቂ')
        self.assertEqual(_('In-Person Consultation'), 'በአካል ምክክር')
        deactivate()



class FacilityLocatorTestCase(APITestCase):

    def setUp(self):
        self.hospital = Facility.objects.create(
            name="Tikur Anbessa Hospital",
            facility_type="HOSPITAL",
            address="Lideta, Addis Ababa",
            city="Addis Ababa",
            region="Addis Ababa",
            phone_number="+251115511211",
            operating_hours="24/7 Emergency",
            available_services=["Maternal Health", "Emergency", "Pediatrics", "Surgery"],
            latitude=9.015000,
            longitude=38.751000,
        )

        self.pharmacy = Facility.objects.create(
            name="Lion Pharmacy",
            facility_type="PHARMACY",
            address="Piazza, Addis Ababa",
            city="Addis Ababa",
            region="Addis Ababa",
            phone_number="+251111223344",
            operating_hours="Mon-Sun: 8:00 AM - 10:00 PM",
            available_services=["Maternal Prescription", "OTC Drugs"],
            latitude=9.035000,
            longitude=38.752000,
        )

    def test_search_and_filter_facilities_by_type(self):
        url = reverse("facility-list")
        res = self.client.get(url, {"facility_type": "PHARMACY"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Lion Pharmacy")

    def test_gps_distance_calculation_and_sorting(self):
        url = reverse("facility-list")
        # Query near Piazza (lat=9.035, lng=38.752)
        res = self.client.get(url, {"lat": "9.035000", "lng": "38.752000"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(results), 2)
        # Lion Pharmacy should be closest (distance near 0 km)
        self.assertEqual(results[0]["name"], "Lion Pharmacy")
        self.assertIsNotNone(results[0]["distance_km"])
        self.assertLess(results[0]["distance_km"], 0.1)


    def test_facility_directions_endpoint(self):
        url = reverse("facility-directions", kwargs={"pk": self.hospital.id})
        res = self.client.get(url, {"lat": "9.030000", "lng": "38.740000"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["facility"]["name"], "Tikur Anbessa Hospital")
        self.assertIn("distance_km", res.data)
        self.assertIn("google_maps", res.data["navigation_urls"])
        self.assertEqual(res.data["call_url"], "tel:+251115511211")


@override_settings(
    SECURE_SSL_REDIRECT=False,
    ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
)
class AdminDashboardAPITestCase(APITestCase):
    """Tests for /api/v1/admin/dashboard/ and /api/v1/admin/midwives/{id}/stats/."""

    def setUp(self):
        from apps.midwives.models import MidwifeProfile, Hospital
        from apps.appointments.models import Appointment
        from apps.consultations.models import Consultation
        from apps.common.models import AuditLog
        from apps.common.utils import log_audit

        self.admin = User.objects.create_superuser(
            username="stats_admin",
            email="stats-admin@example.com",
            password="AdminPassword123!",
            role="ADMIN",
        )
        self.patient = User.objects.create_user(
            username="stats_patient",
            email="patient@example.com",
            password="Password123!",
            role="PATIENT",
        )
        self.midwife_user = User.objects.create_user(
            username="stats_midwife",
            email="midwife@example.com",
            password="Password123!",
            role="MIDWIFE",
        )
        self.hospital = Hospital.objects.create(
            name="Test Hospital",
            address="Addis Ababa",
            phone="+251111111111",
        )
        self.midwife_profile = MidwifeProfile.objects.create(
            user=self.midwife_user,
            hospital=self.hospital,
            license_number="MW-STATS-001",
            verification_status=MidwifeProfile.VerificationStatus.APPROVED,
        )

        # Seed one appointment + linked consultation for the midwife stats endpoint.
        self.appointment = Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type="VIRTUAL_VOICE",
            scheduled_date="2026-09-10",
            start_time="10:00:00",
            end_time="10:30:00",
            status=Appointment.AppointmentStatus.CONFIRMED,
            created_by=self.patient,
        )
        self.consultation = Consultation.objects.create(
            appointment=self.appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="VIRTUAL_VOICE",
            status=Consultation.ConsultationStatus.SCHEDULED,
        )

        # Seed an audit row so the dashboard activity feed is non-empty.
        log_audit(user=self.admin, action="MIDWIFE_VERIFY_APPROVE", details={"midwife_id": str(self.midwife_profile.id)})

    def test_dashboard_requires_admin(self):
        """Non-admin users must not access platform-wide dashboard statistics."""
        self.client.force_authenticate(user=self.patient)
        response = self.client.get(reverse("admin-dashboard"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_dashboard_returns_totals_and_breakdowns(self):
        """Admin dashboard returns aggregate counts and status maps."""
        self.client.force_authenticate(user=self.admin)
        response = self.client.get(reverse("admin-dashboard"))

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("totals", response.data)
        self.assertGreaterEqual(response.data["totals"]["users"], 3)
        self.assertGreaterEqual(response.data["totals"]["midwives"], 1)
        self.assertGreaterEqual(response.data["totals"]["consultations"], 1)
        self.assertEqual(response.data["totals"]["appointments"]["CONFIRMED"], 1)
        self.assertIn("CONFIRMED", response.data["appointments_by_status"])
        self.assertIn("SCHEDULED", response.data["consultations_by_status"])
        self.assertGreaterEqual(len(response.data["recent_activities"]), 1)

    def test_midwife_stats_returns_per_status_counts(self):
        """Selecting one midwife returns consultation/appointment stats with status breakdown."""
        self.client.force_authenticate(user=self.admin)
        url = reverse("admin-midwife-stats", kwargs={"pk": self.midwife_profile.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["midwife"]["license_number"], "MW-STATS-001")
        self.assertEqual(response.data["totals"]["consultations"], 1)
        self.assertEqual(response.data["totals"]["appointments"], 1)
        self.assertEqual(response.data["consultations_by_status"]["SCHEDULED"], 1)
        self.assertEqual(response.data["appointments_by_status"]["CONFIRMED"], 1)
        self.assertEqual(len(response.data["recent_consultations"]), 1)
        self.assertEqual(len(response.data["recent_appointments"]), 1)

    def test_midwife_stats_not_found(self):
        """Unknown midwife profile IDs return a 404."""
        self.client.force_authenticate(user=self.admin)
        url = reverse(
            "admin-midwife-stats",
            kwargs={"pk": "00000000-0000-0000-0000-000000000001"},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


@override_settings(SECURE_SSL_REDIRECT=False)
class AdminDirectoryManagementAPITestCase(APITestCase):
    """Coverage for admin notifications, emergency contacts, and hospitals."""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="directory_admin",
            email="directory-admin@example.com",
            password="AdminPassword123!",
        )
        self.patient = User.objects.create_user(
            username="contact_owner",
            email="contact-owner@example.com",
            password="PatientPassword123!",
        )
        self.client.force_authenticate(user=self.admin)

    def test_admin_can_create_and_list_notification(self):
        url = reverse("admin-notification-list-create")
        create_response = self.client.post(
            url,
            {
                "user_id": str(self.patient.id),
                "title": "Clinic update",
                "body": "Your clinic has updated its maternity service hours.",
                "type": Notification.NotificationType.SYSTEM,
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Notification.objects.filter(user=self.patient).count(), 1)

        list_response = self.client.get(url, {"user": str(self.patient.id)})
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        results = list_response.data.get("results", list_response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Clinic update")

    def test_admin_can_create_and_list_emergency_contact(self):
        url = reverse("admin-emergency-contact-list-create")
        create_response = self.client.post(
            url,
            {
                "user_id": str(self.patient.id),
                "name": "Aster Bekele",
                "relationship": "Mother",
                "phone_number": "+251911123456",
                "is_primary": True,
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(EmergencyContact.objects.filter(user=self.patient, is_primary=True).exists())

        list_response = self.client.get(url, {"user": str(self.patient.id)})
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        results = list_response.data.get("results", list_response.data)
        self.assertEqual(results[0]["name"], "Aster Bekele")

    def test_admin_can_create_and_list_hospital(self):
        url = reverse("admin-hospital-list-create")
        create_response = self.client.post(
            url,
            {
                "name": "Admin Provisioned Hospital",
                "address": "Bole, Addis Ababa",
                "phone": "+251111234567",
                "latitude": "9.019000",
                "longitude": "38.761000",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED)

        list_response = self.client.get(url, {"search": "Provisioned"})
        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        results = list_response.data.get("results", list_response.data)
        self.assertEqual(results[0]["name"], "Admin Provisioned Hospital")

    def test_non_admin_cannot_manage_admin_collections(self):
        self.client.force_authenticate(user=self.patient)
        for name in (
            "admin-notification-list-create",
            "admin-emergency-contact-list-create",
            "admin-hospital-list-create",
        ):
            self.assertEqual(self.client.get(reverse(name)).status_code, status.HTTP_403_FORBIDDEN)

