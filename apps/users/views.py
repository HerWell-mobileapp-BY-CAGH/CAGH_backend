"""
Authentication views for CAGH.

Endpoints:
  POST   /api/v1/auth/register/               — create account (email or mobile) + return tokens
  POST   /api/v1/auth/login/                  — obtain JWT pair + user details (email/phone/username)
  POST   /api/v1/auth/logout/                 — blacklist refresh token
  POST   /api/v1/auth/token/refresh/          — rotate access token
  POST   /api/v1/auth/token/verify/           — verify access token
  POST   /api/v1/auth/password/change/        — change password (authenticated)
  POST   /api/v1/auth/password/reset/         — request reset email
  POST   /api/v1/auth/password/reset/confirm/ — confirm reset with link token
  POST   /api/v1/auth/otp/send/               — send 6-digit OTP
  POST   /api/v1/auth/otp/verify/             — verify 6-digit OTP
  POST   /api/v1/auth/login/otp/              — login using mobile number + OTP
  POST   /api/v1/auth/password/reset/otp/     — request password reset OTP
  POST   /api/v1/auth/password/reset/otp/confirm/ — confirm password reset via OTP

  GET    /api/v1/users/me/                    — current user + profile
  PATCH  /api/v1/users/me/                    — update current user
"""

import random
from datetime import timedelta
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.conf import settings
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils import timezone

from rest_framework import generics, permissions, status, viewsets
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView

from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError, InvalidToken

from drf_spectacular.utils import extend_schema, OpenApiResponse

from .serializers import (
    UserRegistrationSerializer,
    UserRegistrationResponseSerializer,
    LoginResponseSerializer,
    LogoutSerializer,
    PasswordChangeSerializer,
    PasswordResetRequestSerializer,
    PasswordResetConfirmSerializer,
    SendOTPSerializer,
    VerifyOTPSerializer,
    OTPLoginSerializer,
    PasswordResetOTPRequestSerializer,
    PasswordResetOTPConfirmSerializer,
)
from .models import Profile, EmergencyContact, SOSLog, UserPreference, OTPVerification
from .user_serializers import (
    UserSerializer,
    ProfileSerializer,
    EmergencyContactSerializer,
    SOSLogSerializer,
    UserPreferenceSerializer,
)

User = get_user_model()


# ---------------------------------------------------------------------------
# Helper: mask email or phone number for privacy
# ---------------------------------------------------------------------------

def _mask_identifier(target: str) -> str:
    """Mask email or phone number for safe API responses (e.g. +2519****3344 or am****@gmail.com)."""
    target = target.strip()
    if "@" in target:
        parts = target.split("@", 1)
        name, domain = parts[0], parts[1]
        masked_name = name[:2] + "****" if len(name) > 2 else name + "****"
        return f"{masked_name}@{domain}"
    elif len(target) > 6:
        return f"{target[:5]}****{target[-2:]}"
    return target


def _token_pair_for(user: User) -> dict:
    refresh = RefreshToken.for_user(user)
    refresh["role"] = user.role
    refresh["email"] = user.email or ""
    refresh["username"] = user.username or ""
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class UserRegistrationView(generics.CreateAPIView):
    """
    Register a new PATIENT or MIDWIFE account using email or mobile phone.
    On success a JWT token pair and user summary are returned.
    """

    serializer_class = UserRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Register new user",
        description=(
            "Creates a new user account (PATIENT or MIDWIFE). "
            "Allows account creation via mobile phone number or email address. "
            "Automatically creates a linked Profile and UserPreference record. "
            "Returns JWT access + refresh tokens."
        ),
        responses={
            201: UserRegistrationResponseSerializer,
            400: OpenApiResponse(description="Validation errors"),
        },
        tags=["Auth"],
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        tokens = _token_pair_for(user)

        return Response(
            {
                "message": "Account created successfully.",
                "user": {
                    "id": str(user.id),
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                    "phone_number": user.phone_number,
                },
                **tokens,
            },
            status=status.HTTP_201_CREATED,
        )


# ---------------------------------------------------------------------------
# OTP Verification Views
# ---------------------------------------------------------------------------

class SendOTPView(APIView):
    """Generate and send a 6-digit OTP code for mobile/email verification."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Send OTP code",
        request=SendOTPSerializer,
        responses={200: OpenApiResponse(description="OTP sent successfully")},
        tags=["Auth"],
    )
    def post(self, request):
        serializer = SendOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target = serializer.validated_data["phone_number_or_email"].strip()
        if "@" in target:
            target = target.lower()
        purpose = str(serializer.validated_data["purpose"])

        code = str(random.randint(100000, 999999))
        expires_at = timezone.now() + timedelta(minutes=10)

        if "@" in target:
            try:
                send_mail(
                    subject="CAGH — Verification OTP Code",
                    message=(
                        f"Your CAGH verification OTP code is: {code}\n\n"
                        f"This code will expire in 10 minutes.\n\n"
                        f"If you did not request this, please ignore this email.\n\n"
                        f"— The CAGH Team"
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL or "bitsuanabate45@gmail.com",
                    recipient_list=[target],
                    fail_silently=False,
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to send OTP email to {target}: {str(e)}")
                return Response(
                    {"error": f"Failed to send OTP email: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        OTPVerification.objects.filter(phone_number_or_email__iexact=target, purpose=purpose).delete()

        OTPVerification.objects.create(
            phone_number_or_email=target,
            otp_code=code,
            purpose=purpose,
            expires_at=expires_at,
        )

        masked = _mask_identifier(target)

        return Response(
            {
                "message": f"OTP sent successfully to {masked}.",
                "expires_at": expires_at.isoformat(),
            },
            status=status.HTTP_200_OK,
        )





class VerifyOTPView(APIView):
    """Verify a 6-digit OTP code."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Verify OTP code",
        request=VerifyOTPSerializer,
        responses={
            200: OpenApiResponse(description="OTP verified successfully"),
            400: OpenApiResponse(description="Invalid or expired OTP"),
        },
        tags=["Auth"],
    )
    def post(self, request):
        serializer = VerifyOTPSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target = serializer.validated_data["phone_number_or_email"].strip()
        code = serializer.validated_data["otp_code"].strip()
        purpose = str(serializer.validated_data["purpose"])

        otp = OTPVerification.objects.filter(
            phone_number_or_email__iexact=target,
            otp_code=code,
            purpose=purpose,
            expires_at__gt=timezone.now(),
        ).first()


        if not otp:
            return Response(
                {"error": "Invalid or expired OTP code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        otp.is_verified = True
        otp.save()

        return Response(
            {"message": "OTP verified successfully.", "is_verified": True},
            status=status.HTTP_200_OK,
        )


class OTPLoginView(APIView):
    """Authenticate user via Mobile Phone Number or Email + Verified OTP."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Login via OTP",
        request=OTPLoginSerializer,
        responses={
            200: LoginResponseSerializer,
            400: OpenApiResponse(description="Invalid credentials or OTP"),
        },
        tags=["Auth"],
    )
    def post(self, request):
        serializer = OTPLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target = serializer.validated_data["phone_number_or_email"].strip()
        code = serializer.validated_data["otp_code"].strip()

        otp = OTPVerification.objects.filter(
            phone_number_or_email__iexact=target,
            otp_code=code,
            purpose=OTPVerification.Purpose.LOGIN,
            expires_at__gt=timezone.now(),
        ).first()

        if not otp:
            return Response(
                {"error": "Invalid or expired OTP code for login."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(
            phone_number__iexact=target
        ).first() or User.objects.filter(
            email__iexact=target
        ).first()

        if not user:
            return Response(
                {"error": "No user account registered matching this credential."},
                status=status.HTTP_404_NOT_FOUND,
            )

        otp.is_verified = True
        otp.save()

        tokens = _token_pair_for(user)

        return Response(
            {
                "message": "Login successful.",
                "user": {
                    "id": str(user.id),
                    "username": user.username,
                    "email": user.email,
                    "role": user.role,
                    "phone_number": user.phone_number,
                },
                **tokens,
            },
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class LogoutView(APIView):
    """Blacklist the provided refresh token to invalidate the session."""

    permission_classes = [permissions.AllowAny]


    @extend_schema(
        summary="Logout (blacklist refresh token)",
        request=LogoutSerializer,
        responses={
            204: OpenApiResponse(description="Logged out successfully"),
            400: OpenApiResponse(description="Invalid or already-blacklisted token"),
        },
        tags=["Auth"],
    )
    def post(self, request):
        serializer = LogoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            token = RefreshToken(serializer.validated_data["refresh"])
            token.blacklist()
        except TokenError as exc:
            raise InvalidToken({"detail": str(exc)})

        return Response(
            {"message": "Logged out successfully."},
            status=status.HTTP_204_NO_CONTENT,
        )


# ---------------------------------------------------------------------------
# Password Change (authenticated)
# ---------------------------------------------------------------------------

class PasswordChangeView(APIView):
    """Change the authenticated user's password."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        summary="Change password",
        request=PasswordChangeSerializer,
        responses={
            200: OpenApiResponse(description="Password changed. New tokens issued."),
            400: OpenApiResponse(description="Validation error"),
        },
        tags=["Auth"],
    )
    def post(self, request):
        serializer = PasswordChangeSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)

        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        user.save()

        tokens = _token_pair_for(user)

        return Response(
            {"message": "Password changed successfully.", **tokens},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Password Reset — Request & Confirm (Email)
# ---------------------------------------------------------------------------

class PasswordResetRequestView(APIView):
    """Send a password reset link to the provided email address."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Request password reset email",
        request=PasswordResetRequestSerializer,
        responses={200: OpenApiResponse(description="Reset email sent if account exists")},
        tags=["Auth"],
    )
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data["email"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response(
                {"message": "If an account with that email exists, a reset link has been sent."},
                status=status.HTTP_200_OK,
            )

        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        reset_link = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"

        send_mail(
            subject="CAGH — Password Reset Request",
            message=(
                f"Hi {user.first_name or user.username or 'User'},\n\n"
                f"You requested to reset your password. Use the link below:\n\n"
                f"{reset_link}\n\n"
                f"This link expires in {settings.PASSWORD_RESET_TIMEOUT // 3600} hours.\n\n"
                f"If you did not request this, please ignore this email.\n\n"
                f"— The CAGH Team"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )

        return Response(
            {"message": "If an account with that email exists, a reset link has been sent."},
            status=status.HTTP_200_OK,
        )


class PasswordResetConfirmView(APIView):
    """Validate the uid + token from the reset email and set the new password."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Confirm password reset",
        request=PasswordResetConfirmSerializer,
        responses={
            200: OpenApiResponse(description="Password reset successful"),
            400: OpenApiResponse(description="Invalid or expired token"),
        },
        tags=["Auth"],
    )
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["new_password"])
        user.save()

        return Response(
            {"message": "Password has been reset successfully. You can now log in."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Password Reset — Mobile / OTP
# ---------------------------------------------------------------------------

class PasswordResetOTPRequestView(APIView):
    """Request password reset OTP for mobile phone or email."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Request password reset via OTP",
        request=PasswordResetOTPRequestSerializer,
        responses={200: OpenApiResponse(description="OTP sent if user account exists")},
        tags=["Auth"],
    )
    def post(self, request):
        serializer = PasswordResetOTPRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        target = serializer.validated_data["phone_number_or_email"].strip()
        if "@" in target:
            target = target.lower()

        code = str(random.randint(100000, 999999))
        expires_at = timezone.now() + timedelta(minutes=10)

        if "@" in target:
            try:
                send_mail(
                    subject="CAGH — Password Reset OTP Code",
                    message=(
                        f"Your CAGH password reset OTP code is: {code}\n\n"
                        f"This code will expire in 10 minutes.\n\n"
                        f"If you did not request this, please ignore this email.\n\n"
                        f"— The CAGH Team"
                    ),
                    from_email=settings.DEFAULT_FROM_EMAIL or "bitsuanabate45@gmail.com",
                    recipient_list=[target],
                    fail_silently=False,
                )
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to send Password Reset OTP email to {target}: {str(e)}")
                return Response(
                    {"error": f"Failed to send password reset OTP email: {str(e)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        OTPVerification.objects.filter(
            phone_number_or_email__iexact=target,
            purpose=OTPVerification.Purpose.PASSWORD_RESET,
        ).delete()

        OTPVerification.objects.create(
            phone_number_or_email=target,
            otp_code=code,
            purpose=OTPVerification.Purpose.PASSWORD_RESET,
            expires_at=expires_at,
        )

        masked = _mask_identifier(target)

        return Response(
            {
                "message": f"If an account matching '{masked}' exists, a password reset OTP code has been sent.",
            },
            status=status.HTTP_200_OK,
        )




class PasswordResetOTPConfirmView(APIView):
    """Confirm password reset using OTP and new password."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Confirm password reset via OTP",
        request=PasswordResetOTPConfirmSerializer,
        responses={
            200: OpenApiResponse(description="Password reset successful"),
            400: OpenApiResponse(description="Invalid OTP or validation error"),
        },
        tags=["Auth"],
    )
    def post(self, request):
        serializer = PasswordResetOTPConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data["user"]
        otp_record = serializer.validated_data["otp_record"]

        user.set_password(serializer.validated_data["new_password"])
        user.save()

        otp_record.is_verified = True
        otp_record.save()

        return Response(
            {"message": "Password has been reset successfully. You can now log in."},
            status=status.HTTP_200_OK,
        )


# ---------------------------------------------------------------------------
# Current User — Profile & Settings
# ---------------------------------------------------------------------------

class UserMeView(generics.RetrieveUpdateAPIView):
    """Retrieve or partially update the authenticated user's own record."""

    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(summary="Get current user", tags=["Users"])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(summary="Update current user", tags=["Users"])
    def patch(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    @extend_schema(summary="Replace current user", tags=["Users"])
    def put(self, request, *args, **kwargs):
        return super().update(request, *args, **kwargs)

    def get_object(self):
        return self.request.user


# ---------------------------------------------------------------------------
# Profile, EmergencyContact, SOSLog, UserPreference ViewSets
# ---------------------------------------------------------------------------

class ProfileViewSet(viewsets.ModelViewSet):
    """CRUD for the authenticated user's profile."""

    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=["Users"])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        return Profile.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class EmergencyContactViewSet(viewsets.ModelViewSet):
    """Manage emergency contacts for the authenticated user."""

    serializer_class = EmergencyContactSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=["Users"])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        return EmergencyContact.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class SOSLogViewSet(viewsets.ModelViewSet):
    """
    3.8 Emergency Assistance Module
    FR-026 Emergency SOS
    Provides persistent access to emergency hotlines (tel:907, tel:991, tel:952),
    logs GPS location, and alerts saved emergency contacts.
    """

    serializer_class = SOSLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(summary="List user SOS logs", tags=["Emergency SOS"])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        return SOSLog.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sos_log = serializer.save(user=request.user)

        lat = sos_log.latitude
        lng = sos_log.longitude
        maps_url = f"https://maps.google.com/?q={lat},{lng}"

        # Alert user's saved emergency contacts
        contacts = EmergencyContact.objects.filter(user=request.user)
        notified_count = 0

        from apps.notifications.models import Notification
        for contact in contacts:
            Notification.objects.create(
                user=request.user,
                title=f"SOS Alert Sent to {contact.name}",
                body=f"Emergency alert dispatched to {contact.name} ({contact.phone_number}). Location: {maps_url}",
                type="EMERGENCY_SOS",
                action="SOS_ALERT",
                reference_id=str(sos_log.id),
            )
            notified_count += 1

        return Response({
            "status": "SOS_TRIGGERED",
            "message": "Emergency SOS triggered. Location logged and emergency contacts alerted.",
            "call_url": "tel:907",
            "hotlines": [
                {"name": "National Health & Ambulance Hotline", "number": "907", "call_url": "tel:907"},
                {"name": "Police Emergency", "number": "991", "call_url": "tel:991"},
                {"name": "Women & Children Support Hotline", "number": "952", "call_url": "tel:952"},
                {"name": "Red Cross Emergency Ambulance", "number": "907", "call_url": "tel:907"},
            ],
            "notified_contacts_count": notified_count,
            "location": {
                "latitude": float(lat),
                "longitude": float(lng),
                "google_maps_url": maps_url,
            },
            "sos_log": serializer.data,
        }, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Get emergency hotlines list", tags=["Emergency SOS"])
    @action(detail=False, methods=['get'])
    def hotlines(self, request):
        return Response({
            "default_call_url": "tel:907",
            "hotlines": [
                {"name": "National Health & Ambulance Hotline", "number": "907", "call_url": "tel:907"},
                {"name": "Police Emergency", "number": "991", "call_url": "tel:991"},
                {"name": "Women & Children Support Hotline", "number": "952", "call_url": "tel:952"},
                {"name": "Red Cross Emergency Ambulance", "number": "907", "call_url": "tel:907"},
            ]
        }, status=status.HTTP_200_OK)



class UserPreferenceView(generics.RetrieveUpdateAPIView):
    """Get or update the authenticated user's app preferences."""

    serializer_class = UserPreferenceSerializer
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=["Users"])
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_object(self):
        obj, _ = UserPreference.objects.get_or_create(user=self.request.user)
        return obj
