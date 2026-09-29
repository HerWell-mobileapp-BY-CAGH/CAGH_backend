"""
Authentication URL routing — /api/v1/auth/

POST  /api/v1/auth/register/              — create account + receive tokens
POST  /api/v1/auth/login/                 — obtain JWT pair + user details (email/phone/username)
POST  /api/v1/auth/logout/                — blacklist refresh token
POST  /api/v1/auth/token/refresh/         — rotate access token (SimpleJWT)
POST  /api/v1/auth/token/verify/          — verify access token (SimpleJWT)
POST  /api/v1/auth/otp/send/               — send 6-digit OTP code
POST  /api/v1/auth/otp/verify/             — verify 6-digit OTP code
POST  /api/v1/auth/login/otp/              — login using mobile number + OTP
POST  /api/v1/auth/password/change/       — change password (authenticated)
POST  /api/v1/auth/password/reset/        — request password reset email
POST  /api/v1/auth/password/reset/confirm/ — confirm reset with link token
POST  /api/v1/auth/password/reset/otp/     — request password reset OTP
POST  /api/v1/auth/password/reset/otp/confirm/ — confirm password reset via OTP
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView, TokenVerifyView

from .authentication import CustomTokenObtainPairView, AdminTokenObtainPairView
from .views import (
    UserRegistrationView,
    LogoutView,
    PasswordChangeView,
    AdminPasswordChangeView,
    PasswordResetRequestView,
    PasswordResetConfirmView,
    SendOTPView,
    VerifyOTPView,
    OTPLoginView,
    PasswordResetOTPRequestView,
    PasswordResetOTPConfirmView,
)

urlpatterns = [
    # ---------- Account ----------
    path("register/", UserRegistrationView.as_view(), name="auth-register"),

    # ---------- JWT ----------
    path("login/", CustomTokenObtainPairView.as_view(), name="auth-login"),
    # A separate endpoint avoids using a client-provided role value as the
    # decision for administrator-dashboard access.
    path("admin/login/", AdminTokenObtainPairView.as_view(), name="auth-admin-login"),
    path("login/otp/", OTPLoginView.as_view(), name="auth-login-otp"),
    path("logout/", LogoutView.as_view(), name="auth-logout"),
    path("token/refresh/", TokenRefreshView.as_view(), name="auth-token-refresh"),
    path("token/verify/", TokenVerifyView.as_view(), name="auth-token-verify"),

    # ---------- OTP Verification ----------
    path("otp/send/", SendOTPView.as_view(), name="auth-otp-send"),
    path("otp/verify/", VerifyOTPView.as_view(), name="auth-otp-verify"),

    # ---------- Password ----------
    path("password/change/", PasswordChangeView.as_view(), name="auth-password-change"),
    path("admin/password/change/", AdminPasswordChangeView.as_view(), name="auth-admin-password-change"),
    path("password/reset/", PasswordResetRequestView.as_view(), name="auth-password-reset"),
    path("password/reset/confirm/", PasswordResetConfirmView.as_view(), name="auth-password-reset-confirm"),
    path("password/reset/otp/", PasswordResetOTPRequestView.as_view(), name="auth-password-reset-otp"),
    path("password/reset/otp/confirm/", PasswordResetOTPConfirmView.as_view(), name="auth-password-reset-otp-confirm"),
]
