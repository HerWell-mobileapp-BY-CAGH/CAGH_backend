from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from apps.users.models import Profile
from apps.common.models import Facility


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

