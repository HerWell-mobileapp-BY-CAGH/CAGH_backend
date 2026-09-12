from datetime import date
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model

from apps.midwives.models import MidwifeProfile, Hospital
from apps.appointments.models import Appointment
from apps.consultations.models import Consultation
from apps.reviews.models import Review

User = get_user_model()


class ReviewsTestCase(APITestCase):

    def setUp(self):
        self.patient = User.objects.create_user(
            username="patient_rev",
            email="patient_rev@example.com",
            password="PatientPassword123!",
        )

        self.midwife_user = User.objects.create_user(
            username="midwife_rev",
            email="midwife_rev@example.com",
            password="MidwifePassword123!",
            role="MIDWIFE",
        )
        self.hospital = Hospital.objects.create(name="Black Lion Hospital", address="Addis Ababa")
        self.midwife_profile = MidwifeProfile.objects.create(
            user=self.midwife_user,
            hospital=self.hospital,
            license_number="MW-REV-500",
            verification_status="APPROVED",
        )
        self.admin = User.objects.create_user(
            username="reviews_admin",
            email="reviews-admin@example.com",
            password="AdminPassword123!",
            role="ADMIN",
            is_staff=True,
        )

        self.appointment = Appointment.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            appointment_type="IN_PERSON",
            scheduled_date=date.today(),
            start_time="09:00:00",
            end_time="09:30:00",
            status="COMPLETED",
            created_by=self.patient,
        )

        self.consultation = Consultation.objects.create(
            appointment=self.appointment,
            user=self.patient,
            midwife=self.midwife_profile,
            consultation_type="IN_PERSON",
            status="COMPLETED",
        )

    def test_leave_review_and_recalculate_midwife_rating(self):
        self.client.force_authenticate(user=self.patient)
        url = reverse("review-list")
        data = {
            "midwife": str(self.midwife_profile.id),
            "consultation": str(self.consultation.id),
            "rating": 5,
            "comment": "Outstanding healthcare support and advice!",
            "is_anonymous": False,
        }
        res = self.client.post(url, data, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["reviewer_name"], self.patient.username)

        # Verify Midwife Profile Rating Update
        self.midwife_profile.refresh_from_db()
        self.assertEqual(self.midwife_profile.rating_count, 1)
        self.assertEqual(float(self.midwife_profile.rating_average), 5.0)

    def test_anonymous_review(self):
        self.client.force_authenticate(user=self.patient)
        url = reverse("review-list")
        data = {
            "midwife": str(self.midwife_profile.id),
            "rating": 4,
            "comment": "Great experience.",
            "is_anonymous": True,
        }
        res = self.client.post(url, data, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["reviewer_name"], "Anonymous")

    def test_admin_can_list_public_reviews_and_reviews_for_a_midwife(self):
        review = Review.objects.create(
            user=self.patient,
            midwife=self.midwife_profile,
            rating=5,
            comment="Very helpful.",
        )
        self.client.force_authenticate(user=self.admin)

        public_response = self.client.get(reverse("admin-public-review-list"))
        midwife_response = self.client.get(
            reverse("admin-midwife-review-list", kwargs={"midwife_id": self.midwife_profile.id})
        )

        self.assertEqual(public_response.status_code, status.HTTP_200_OK)
        self.assertEqual(midwife_response.status_code, status.HTTP_200_OK)
        public_results = public_response.data.get("results", public_response.data)
        midwife_results = midwife_response.data.get("results", midwife_response.data)
        self.assertEqual(str(public_results[0]["id"]), str(review.id))
        self.assertEqual(str(midwife_results[0]["id"]), str(review.id))

    def test_non_admin_cannot_list_admin_reviews(self):
        self.client.force_authenticate(user=self.patient)
        response = self.client.get(reverse("admin-public-review-list"))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
