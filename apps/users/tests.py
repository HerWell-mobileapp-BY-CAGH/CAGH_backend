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

