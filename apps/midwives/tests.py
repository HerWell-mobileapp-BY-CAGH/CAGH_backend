from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from apps.midwives.models import MidwifeProfile, Hospital, Qualification, Certificate, BlockedDate
from apps.notifications.models import Notification

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

        # Suspend (requires reason)
        suspend_res = self.client.post(
            url,
            {"action": "SUSPEND", "reason": "License verification failed during audit."},
            format="json",
        )
        self.assertEqual(suspend_res.status_code, status.HTTP_200_OK)
        self.midwife_profile.refresh_from_db()
        self.assertEqual(self.midwife_profile.verification_status, "SUSPENDED")
        self.assertIn("audit", self.midwife_profile.suspension_reason)

    def test_midwife_dashboard(self):
        self.client.force_authenticate(user=self.midwife_user)
        url = reverse("midwife-dashboard")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("verification_status", response.data)
        self.assertIn("today_schedule", response.data)
        self.assertIn("counts", response.data)

    def test_midwife_blocked_dates(self,):
        # Unverified midwife attempt -> 403 Forbidden
        self.midwife_profile.verification_status = "PENDING"
        self.midwife_profile.save()
        self.client.force_authenticate(user=self.midwife_user)
        url = reverse("midwife-blocked-date-list")
        create_res_pending = self.client.post(url, {"date": "2026-09-15", "reason": "Annual leave"}, format="json")
        self.assertEqual(create_res_pending.status_code, status.HTTP_403_FORBIDDEN)

        # Verified midwife attempt -> 201 Created
        self.midwife_profile.verification_status = "APPROVED"
        self.midwife_profile.save()
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


class MidwifeAuthenticationWorkflowTestCase(APITestCase):

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="review_admin",
            email="review-admin@example.com",
            password="AdminPassword123!",
            role="ADMIN",
        )
        self.midwife_user = User.objects.create_user(
            username="pending_midwife",
            email="pending@example.com",
            password="MidwifePassword123!",
            role="MIDWIFE",
        )
        self.hospital = Hospital.objects.create(
            name="Tikur Anbessa",
            address="Addis Ababa",
            phone="+251111223344",
        )
        self.profile = MidwifeProfile.objects.create(
            user=self.midwife_user,
            hospital=self.hospital,
            license_number="MW-123456",
            experience_years=8,
            bio="Certified midwife with 8 years of experience.",
            languages="English, Amharic",
            cv_file="midwives/cvs/sample_cv.pdf",
            verification_status=MidwifeProfile.VerificationStatus.PENDING,
        )
        Qualification.objects.create(
            midwife=self.profile,
            title="BSc Midwifery",
            institution="Addis Ababa University",
            year_obtained=2016,
        )
        Certificate.objects.create(
            midwife=self.profile,
            title="Midwifery License",
            document_file="midwives/certificates/license.pdf",
        )

    def test_admin_can_list_pending_applications_with_full_details(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse("midwife-applications-list")
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get("results", response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["license_number"], "MW-123456")
        self.assertEqual(len(results[0]["qualifications"]), 1)
        self.assertEqual(len(results[0]["certificates"]), 1)
        self.assertIn("user", results[0])

    def test_admin_can_fetch_single_application_detail(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse("midwife-application-detail", kwargs={"pk": self.profile.id})
        response = self.client.get(url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["verification_status"], "PENDING")
        self.assertEqual(response.data["user"]["email"], "pending@example.com")

    def test_admin_can_approve_application(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse("midwife-application-review", kwargs={"pk": self.profile.id})
        response = self.client.post(url, {"action": "APPROVE"}, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "APPROVED")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, "APPROVED")
        self.assertEqual(self.profile.verified_by, self.admin)
        self.assertTrue(
            Notification.objects.filter(
                user=self.midwife_user,
                action="MIDWIFE_REVIEW",
            ).exists()
        )

    def test_admin_reject_requires_reason(self):
        self.client.force_authenticate(user=self.admin)
        url = reverse("midwife-application-review", kwargs={"pk": self.profile.id})

        missing_reason = self.client.post(url, {"action": "REJECT"}, format="json")
        self.assertEqual(missing_reason.status_code, status.HTTP_400_BAD_REQUEST)

        rejected = self.client.post(
            url,
            {
                "action": "REJECT",
                "reason": "Uploaded license document is expired and cannot be verified.",
            },
            format="json",
        )
        self.assertEqual(rejected.status_code, status.HTTP_200_OK)
        self.assertEqual(rejected.data["status"], "REJECTED")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.verification_status, "REJECTED")
        self.assertIn("expired", self.profile.rejection_reason)

    def test_pending_midwife_can_login_but_is_not_patient_visible(self):
        login_url = reverse("auth-login")
        allowed = self.client.post(
            login_url,
            {"email": "pending@example.com", "password": "MidwifePassword123!", "role": "MIDWIFE"},
            format="json",
        )
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)
        self.assertIn("access", allowed.data)
        self.assertEqual(
            allowed.data["user"]["midwife_profile"]["verification_status"],
            "PENDING",
        )

        # Patients must not see pending midwives in the directory
        self.client.force_authenticate(user=None)
        patient = User.objects.create_user(
            username="patient_viewer",
            email="viewer@example.com",
            password="PatientPassword123!",
            role="PATIENT",
        )
        self.client.force_authenticate(user=patient)
        list_url = reverse("midwife-profile-list")
        listed = self.client.get(list_url)
        results = listed.data.get("results", listed.data)
        self.assertEqual(len(results), 0)

    def test_rejected_midwife_can_login_and_sees_rejection_reason(self):
        self.profile.verification_status = MidwifeProfile.VerificationStatus.REJECTED
        self.profile.rejection_reason = "Invalid license number."
        self.profile.save()

        login_url = reverse("auth-login")
        response = self.client.post(
            login_url,
            {"email": "pending@example.com", "password": "MidwifePassword123!", "role": "MIDWIFE"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["user"]["midwife_profile"]["rejection_reason"],
            "Invalid license number.",
        )

    def test_non_admin_cannot_review_applications(self):
        self.client.force_authenticate(user=self.midwife_user)
        url = reverse("midwife-application-review", kwargs={"pk": self.profile.id})
        response = self.client.post(url, {"action": "APPROVE"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_suspended_midwife_can_login_and_sees_suspension_reason(self):
        self.profile.verification_status = MidwifeProfile.VerificationStatus.APPROVED
        self.profile.save()

        self.client.force_authenticate(user=self.admin)
        review_url = reverse("midwife-application-review", kwargs={"pk": self.profile.id})
        self.client.post(
            review_url,
            {"action": "SUSPEND", "reason": "Repeated no-shows for scheduled appointments."},
            format="json",
        )

        login_url = reverse("auth-login")
        response = self.client.post(
            login_url,
            {"email": "pending@example.com", "password": "MidwifePassword123!", "role": "MIDWIFE"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn(
            "Repeated no-shows",
            response.data["user"]["midwife_profile"]["suspension_reason"],
        )

    def test_suspend_requires_reason(self):
        self.profile.verification_status = MidwifeProfile.VerificationStatus.APPROVED
        self.profile.save()
        self.client.force_authenticate(user=self.admin)
        url = reverse("midwife-application-review", kwargs={"pk": self.profile.id})
        response = self.client.post(url, {"action": "SUSPEND"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_pending_midwife_can_access_dashboard(self):
        refresh = RefreshToken.for_user(self.midwife_user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")
        dashboard_url = reverse("midwife-dashboard")
        allowed = self.client.get(dashboard_url)
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)
        self.assertEqual(allowed.data["verification_status"], "PENDING")

    def test_midwife_registration_issues_tokens_with_pending_status(self):
        register_url = reverse("auth-register")
        register_res = self.client.post(
            register_url,
            {
                "email": "new-midwife@example.com",
                "password": "MidwifePassword123!",
                "password_confirm": "MidwifePassword123!",
                "role": "MIDWIFE",
            },
            format="json",
        )
        self.assertEqual(register_res.status_code, status.HTTP_201_CREATED)
        self.assertTrue(register_res.data.get("requires_admin_approval"))
        self.assertIn("access", register_res.data)
        self.assertIn("refresh", register_res.data)
