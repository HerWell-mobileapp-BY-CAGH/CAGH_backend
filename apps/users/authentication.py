"""
Custom JWT serializers for CAGH Authentication.

- CustomTokenObtainPairSerializer: injects user claims into the JWT payload
  and returns user details alongside the token pair on login. Supports login via
  email, mobile phone number, or username without requiring username explicitly.
- CustomTokenObtainPairView: wires the serializer to the DRF view.
"""

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.exceptions import AuthenticationFailed
from rest_framework import serializers
from django.contrib.auth import authenticate


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """
    Extends default login serializer to allow login with:
    - Email address + password
    - Phone number + password
    - Username + password
    Does NOT require 'username' field explicitly in the payload.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields[self.username_field].required = False
        self.fields[self.username_field].allow_blank = True

        self.fields["email"] = serializers.CharField(required=False, write_only=True)
        self.fields["phone_number"] = serializers.CharField(required=False, write_only=True)
        self.fields["login"] = serializers.CharField(required=False, write_only=True)
        self.fields["role"] = serializers.CharField(required=False, write_only=True)
        self.fields["expected_role"] = serializers.CharField(required=False, write_only=True)

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token["role"] = user.role
        token["email"] = user.email or ""
        token["username"] = user.username or ""
        return token

    def validate(self, attrs):
        login_identifier = (
            attrs.get("username")
            or attrs.get("email")
            or attrs.get("phone_number")
            or attrs.get("login")
        )

        if not login_identifier:
            raise serializers.ValidationError(
                {"login": "Mobile Phone Number or Email Address is required."}
            )

        attrs[self.username_field] = login_identifier

        user = authenticate(
            request=self.context.get("request"),
            username=login_identifier,
            password=attrs.get("password"),
        )

        if not user:
            raise AuthenticationFailed(
                "No active account found with the given credentials",
                code="no_active_account",
            )

        from apps.users.models import User

        # Auto-heal: If user has a MidwifeProfile attached, ensure DB role is MIDWIFE
        if hasattr(user, 'midwife_profile') and user.role != User.Role.MIDWIFE:
            user.role = User.Role.MIDWIFE
            user.save(update_fields=['role'])

        # Auto-heal: If user.role is MIDWIFE but lacks MidwifeProfile, create default profile
        if user.role == User.Role.MIDWIFE and not hasattr(user, 'midwife_profile'):
            from apps.midwives.models import MidwifeProfile
            import uuid
            MidwifeProfile.objects.get_or_create(
                user=user,
                defaults={
                    "license_number": f"LIC-{uuid.uuid4().hex[:8].upper()}",
                    "verification_status": MidwifeProfile.VerificationStatus.PENDING,
                    "is_accepting_bookings": False,
                }
            )

        req = self.context.get("request")
        requested_role_raw = (
            attrs.get("role")
            or attrs.get("expected_role")
            or self.initial_data.get("role")
            or self.initial_data.get("expected_role")
        )
        if not requested_role_raw and req:
            req_data = getattr(req, "data", {}) or {}
            requested_role_raw = (
                req_data.get("role")
                or req_data.get("expected_role")
                or req.query_params.get("role")
                or req.query_params.get("expected_role")
                or req.headers.get("X-Role")
                or req.headers.get("x-role")
            )

        from apps.users.models import User

        # Auto-heal: If user has a MidwifeProfile attached, ensure DB role is MIDWIFE
        if hasattr(user, 'midwife_profile') and user.role != User.Role.MIDWIFE:
            user.role = User.Role.MIDWIFE
            user.save(update_fields=['role'])

        # Auto-heal: If user.role is MIDWIFE but lacks MidwifeProfile, create default profile
        if user.role == User.Role.MIDWIFE and not hasattr(user, 'midwife_profile'):
            from apps.midwives.models import MidwifeProfile
            MidwifeProfile.objects.get_or_create(
                user=user,
                defaults={
                    "verification_status": MidwifeProfile.VerificationStatus.PENDING,
                    "license_number": f"LIC-{user.id.hex[:8].upper()}",
                }
            )

        # Determine target requested role (if omitted by frontend login, default to user's registered role)
        target_requested_role = requested_role_raw or user.role

        normalized_requested = User.Role.normalize(target_requested_role)
        normalized_user_role = User.Role.normalize(user.role)

        if requested_role_raw and normalized_user_role != normalized_requested and not user.is_staff:
            raise AuthenticationFailed(
                f"Access denied: This account is registered as a {user.role} and cannot log in as a {normalized_requested}.",
                code="role_mismatch",
            )

        self.user = user
        refresh = self.get_token(self.user)

        from apps.users.user_serializers import UserSerializer

        data = {
            "refresh": str(refresh),
            "access": str(refresh.access_token),
            "user": UserSerializer(self.user).data,
        }

        return data


class CustomTokenObtainPairView(TokenObtainPairView):
    """POST /api/v1/auth/login/ — returns access + refresh token plus user details."""

    serializer_class = CustomTokenObtainPairSerializer


class AdminTokenObtainPairSerializer(CustomTokenObtainPairSerializer):
    """Issue JWTs only to accounts provisioned for the administrator dashboard."""

    def validate(self, attrs):
        # Reuse the identifier/password handling and standard token response.
        data = super().validate(attrs)

        from apps.users.models import User

        # Requiring both values prevents a user whose role changed accidentally
        # from receiving dashboard credentials. `createsuperuser` and
        # `reset_admin` create legitimate accounts with both values.
        if (
            User.Role.normalize(self.user.role) != User.Role.ADMIN
            or not self.user.is_staff
        ):
            raise AuthenticationFailed(
                "This account is not authorized to access the administrator dashboard.",
                code="admin_access_required",
            )

        # This explicitly tells the client which interface the JWT was issued for.
        data["login_role"] = User.Role.ADMIN
        return data


class AdminTokenObtainPairView(TokenObtainPairView):
    """Administrator-only JWT sign-in endpoint."""

    serializer_class = AdminTokenObtainPairSerializer
