from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from apps.users.models import OTPVerification

User = get_user_model()


class AuthenticationTestCase(APITestCase):

    def test_email_registration_without_username(self):
        url = reverse("auth-register")
        data = {
            "email": "patient@example.com",
            "password": "SecurePassword123!",
            "password_confirm": "SecurePassword123!",
            "full_name": "Jane Doe",
            "gender": "FEMALE",
            "region": "Greater Accra",
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)
        self.assertEqual(response.data["user"]["email"], "patient@example.com")

        # Verify profile creation
        user = User.objects.get(email="patient@example.com")
        self.assertIsNotNone(user.username)
        self.assertEqual(user.profile.first_name, "Jane")
        self.assertEqual(user.profile.last_name, "Doe")
        self.assertEqual(user.profile.gender, "FEMALE")
        self.assertEqual(user.profile.region, "Greater Accra")

    def test_phone_registration_without_username(self):
        url = reverse("auth-register")
        data = {
            "phone_number": "+233501234567",
            "password": "SecurePassword123!",
            "password_confirm": "SecurePassword123!",
            "first_name": "Kwame",
            "last_name": "Mensah",
            "gender": "MALE",
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["user"]["phone_number"], "+233501234567")

        user = User.objects.get(phone_number="+233501234567")
        self.assertIsNotNone(user.username)
        self.assertEqual(user.profile.gender, "MALE")

    def test_login_with_email_without_username_field(self):
        user = User.objects.create_user(
            username="user_email_test",
            email="login_email@example.com",
            password="MySecretPassword123!",
        )
        url = reverse("auth-login")
        data = {
            "email": "login_email@example.com",
            "password": "MySecretPassword123!",
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertEqual(response.data["user"]["email"], "login_email@example.com")

    def test_login_with_phone_without_username_field(self):
        user = User.objects.create_user(
            username="user_phone_test",
            email="phone_user@example.com",
            phone_number="+233240000000",
            password="MySecretPassword123!",
        )
        url = reverse("auth-login")
        data = {
            "phone_number": "+233240000000",
            "password": "MySecretPassword123!",
        }
        response = self.client.post(url, data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_otp_send_and_verify(self):
        send_url = reverse("auth-otp-send")
        data = {
            "phone_number_or_email": "+233559998877",
            "purpose": "REGISTRATION",
        }
        send_response = self.client.post(send_url, data, format="json")
        self.assertEqual(send_response.status_code, status.HTTP_200_OK)

        otp_record = OTPVerification.objects.get(phone_number_or_email="+233559998877", purpose="REGISTRATION")

        verify_url = reverse("auth-otp-verify")
        verify_data = {
            "phone_number_or_email": "+233559998877",
            "otp_code": otp_record.otp_code,
            "purpose": "REGISTRATION",
        }
        verify_response = self.client.post(verify_url, verify_data, format="json")
        self.assertEqual(verify_response.status_code, status.HTTP_200_OK)
        self.assertTrue(verify_response.data["is_verified"])

    def test_otp_password_reset_flow(self):
        user = User.objects.create_user(
            username="reset_test",
            phone_number="+233201112233",
            password="OldPassword123!",
        )
        # Send OTP
        reset_req_url = reverse("auth-password-reset-otp")
        req_res = self.client.post(reset_req_url, {"phone_number_or_email": "+233201112233"}, format="json")
        self.assertEqual(req_res.status_code, status.HTTP_200_OK)

        otp_record = OTPVerification.objects.get(phone_number_or_email="+233201112233", purpose="PASSWORD_RESET")

        # Confirm Password Reset
        reset_confirm_url = reverse("auth-password-reset-otp-confirm")
        confirm_data = {
            "phone_number_or_email": "+233201112233",
            "otp_code": otp_record.otp_code,
            "new_password": "NewSecurePassword123!",
            "new_password_confirm": "NewSecurePassword123!",
        }
        confirm_res = self.client.post(reset_confirm_url, confirm_data, format="json")
        self.assertEqual(confirm_res.status_code, status.HTTP_200_OK)

        # Login with new password
        login_url = reverse("auth-login")
        login_res = self.client.post(login_url, {"phone_number": "+233201112233", "password": "NewSecurePassword123!"}, format="json")
        self.assertEqual(login_res.status_code, status.HTTP_200_OK)


class UserManagementTestCase(APITestCase):

    def setUp(self):
        self.user = User.objects.create_user(
            username="test_patient",
            email="patient_mgmt@example.com",
            phone_number="+251911223344",
            password="TestPassword123!",
        )
        self.client.force_authenticate(user=self.user)

    def test_get_and_update_user_me(self):
        url = reverse("user-me")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["email"], "patient_mgmt@example.com")

        # Update profile
        patch_res = self.client.patch(url, {"profile": {"first_name": "Sara", "city": "Addis Ababa"}}, format="json")
        self.assertEqual(patch_res.status_code, status.HTTP_200_OK)

    def test_user_preferences(self):
        url = reverse("user-preferences")
        get_res = self.client.get(url)
        self.assertEqual(get_res.status_code, status.HTTP_200_OK)

        patch_res = self.client.patch(url, {"dark_mode": True, "push_notifications": False}, format="json")
        self.assertEqual(patch_res.status_code, status.HTTP_200_OK)
        self.assertTrue(patch_res.data["dark_mode"])
        self.assertFalse(patch_res.data["push_notifications"])

    def test_emergency_contacts_crud(self):
        list_url = reverse("emergency-contact-list")
        # Create contact
        create_res = self.client.post(
            list_url,
            {"name": "Mother", "relationship": "Parent", "phone_number": "+251922334455", "is_primary": True},
            format="json",
        )
        self.assertEqual(create_res.status_code, status.HTTP_201_CREATED)
        contact_id = create_res.data["id"]

        # List contacts
        list_res = self.client.get(list_url)
        self.assertEqual(list_res.status_code, status.HTTP_200_OK)
        results = list_res.data.get("results", list_res.data)
        self.assertEqual(len(results), 1)


        # Delete contact
        detail_url = reverse("emergency-contact-detail", kwargs={"pk": contact_id})
        del_res = self.client.delete(detail_url)
        self.assertEqual(del_res.status_code, status.HTTP_204_NO_CONTENT)

    def test_sos_log_trigger(self):
        url = reverse("sos-log-list")
        res = self.client.post(url, {"latitude": "9.030000", "longitude": "38.740000"}, format="json")
        self.assertEqual(res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(res.data["status"], "SOS_TRIGGERED")
        self.assertEqual(res.data["call_url"], "tel:907")
        self.assertIn("hotlines", res.data)
        self.assertIn("location", res.data)

    def test_sos_hotlines_endpoint(self):
        url = reverse("sos-log-hotlines")
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["default_call_url"], "tel:907")
        self.assertGreater(len(res.data["hotlines"]), 0)



