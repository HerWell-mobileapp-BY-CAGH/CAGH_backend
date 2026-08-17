from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from apps.midwives.models import MidwifeProfile, Hospital, Qualification, BlockedDate

User = get_user_model()


class MidwifeManagementTestCase(APITestCase):

    def setUp(self):
        # Create Admin
        self.admin = User.objects.create_superuser(
            username="admin_user",
            email="admin@example.com",
            password="AdminPassword123!",
            role="ADMIN",
        )

        # Create Midwife User & Profile
        self.midwife_user = User.objects.create_user(
            username="midwife_mary",
            email="mary@example.com",
            phone_number="+251911998877",
            password="MidwifePassword123!",
            role="MIDWIFE",
        )
        self.hospital = Hospital.objects.create(
            name="Saint Paul Hospital",
            address="Addis Ababa",
            phone="+251111223344",
        )
        self.midwife_profile = MidwifeProfile.objects.create(
            user=self.midwife_user,
            hospital=self.hospital,
            license_number="MW-998877",
            experience_years=5,
            bio="Experienced certified midwife specializing in adolescent maternal care.",
            languages="English, Amharic, Oromiffa",
            cv_file="midwives/cvs/mary_cv.pdf",
            offered_consultation_types=["IN_PERSON", "VIRTUAL_VOICE"],
        )

        # Create Patient User
        self.patient_user = User.objects.create_user(
            username="patient_sara",
            email="sara@example.com",
            password="PatientPassword123!",
            role="PATIENT",
        )

    def test_midwife_profile_me(self):
        self.client.force_authenticate(user=self.midwife_user)
        url = reverse("midwife-profile-me")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["license_number"], "MW-998877")

        # Partial update profile
        patch_res = self.client.patch(url, {"experience_years": 6, "languages": "English, Amharic"}, format="json")
        self.assertEqual(patch_res.status_code, status.HTTP_200_OK)
        self.assertEqual(patch_res.data["experience_years"], 6)

    def test_admin_approval_workflow(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse("midwife-profile-verify", kwargs={"pk": self.midwife_profile.id})

        # Approve
        res = self.client.post(url, {"action": "APPROVE"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.midwife_profile.refresh_from_db()
        self.assertEqual(self.midwife_profile.verification_status, "APPROVED")

        # Suspend
        suspend_res = self.client.post(url, {"action": "SUSPEND"}, format="json")
        self.assertEqual(suspend_res.status_code, status.HTTP_200_OK)
        self.midwife_profile.refresh_from_db()
        self.assertEqual(self.midwife_profile.verification_status, "SUSPENDED")

    def test_midwife_dashboard(self):
        self.client.force_authenticate(user=self.midwife_user)
        url = reverse("midwife-dashboard")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("verification_status", response.data)
        self.assertIn("today_schedule", response.data)
        self.assertIn("counts", response.data)

    def test_midwife_blocked_dates(self):
        self.client.force_authenticate(user=self.midwife_user)
        url = reverse("midwife-blocked-date-list")
        create_res = self.client.post(url, {"date": "2026-09-15", "reason": "Annual leave"}, format="json")
        self.assertEqual(create_res.status_code, status.HTTP_201_CREATED)

        list_res = self.client.get(url)
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        results = list_res.data.get("results", list_res.data)
        self.assertEqual(len(results), 1)

    def test_public_midwife_visibility(self):
        # Patient listing midwives should only see APPROVED midwives
        self.client.force_authenticate(user=self.patient_user)
        list_url = reverse("midwife-profile-list")
        res = self.client.get(list_url)
        results = res.data.get("results", res.data)
        self.assertEqual(len(results), 0)  # Profile is currently PENDING

        # Approve midwife
        self.midwife_profile.verification_status = "APPROVED"
        self.midwife_profile.save()

        res_approved = self.client.get(list_url)
        results_approved = res_approved.data.get("results", res_approved.data)
        self.assertEqual(len(results_approved), 1)

    def test_midwife_search_and_favorite_toggle(self):
        self.midwife_profile.verification_status = "APPROVED"
        self.midwife_profile.specialty = "Maternal Health Specialist"
        self.midwife_profile.save()

        self.client.force_authenticate(user=self.patient_user)
        list_url = reverse("midwife-profile-list")

        # Search by specialty
        search_res = self.client.get(f"{list_url}?search=Maternal")
        results = search_res.data.get("results", search_res.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["specialty"], "Maternal Health Specialist")
        self.assertFalse(results[0]["is_favorite"])

        # Toggle favorite
        fav_url = reverse("midwife-profile-favorite", kwargs={"pk": self.midwife_profile.id})
        fav_res = self.client.post(fav_url)
        self.assertEqual(fav_res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(fav_res.data["is_favorite"])

        # Check search again -> is_favorite should be True
        search_fav = self.client.get(f"{list_url}?search=mary")
        results_fav = search_fav.data.get("results", search_fav.data)
        self.assertEqual(len(results_fav), 1)
        self.assertTrue(results_fav[0]["is_favorite"])
