"""
Authentication serializers for CAGH.

Covers:
- UserRegistrationSerializer     — create account (email or mobile, optional username)
- LoginResponseSerializer        — documents login response shape
- LogoutSerializer               — accepts refresh token for blacklisting
- PasswordChangeSerializer       — authenticated password change
- PasswordResetRequestSerializer — email reset request
- PasswordResetConfirmSerializer — email reset confirm
- SendOTPSerializer & VerifyOTPSerializer — OTP generation & verification
- PasswordResetOTPRequestSerializer & PasswordResetOTPConfirmSerializer — mobile OTP password reset
"""

import uuid
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers
from .models import Profile, UserPreference, OTPVerification

User = get_user_model()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class UserRegistrationSerializer(serializers.ModelSerializer):
    """
    Register a new PATIENT or MIDWIFE account.
    Allows registration via email address or mobile phone number.
    Username is optional (auto-generated if omitted).
    """

    username = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=150,
        help_text="Optional. Unique username.",
    )
    email = serializers.EmailField(
        required=False,
        allow_blank=True,
        allow_null=True,
        help_text="Optional if phone_number provided.",
    )
    phone_number = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        max_length=20,
        help_text="Optional if email provided.",
    )
    password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        allow_null=True,
        min_length=8,
        style={"input_type": "password"},
        help_text="Minimum 8 characters.",
    )
    password_confirm = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        allow_null=True,
        style={"input_type": "password"},
        help_text="Must match password.",
    )
    full_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    first_name = serializers.CharField(max_length=100, write_only=True, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=100, write_only=True, required=False, allow_blank=True)
    date_of_birth = serializers.DateField(write_only=True, required=False, allow_null=True)
    gender = serializers.ChoiceField(choices=Profile.Gender.choices, write_only=True, required=False, allow_null=True, allow_blank=True)
    region = serializers.CharField(max_length=100, write_only=True, required=False, allow_blank=True)
    otp_code = serializers.CharField(max_length=6, write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "phone_number",
            "password",
            "password_confirm",
            "role",
            "full_name",
            "first_name",
            "last_name",
            "date_of_birth",
            "gender",
            "region",
            "otp_code",
        )
        extra_kwargs = {
            "role": {"required": False},  # defaults to PATIENT
        }

    def validate_role(self, value):
        initial = getattr(self, "initial_data", {}) or {}
        raw_val = (
            value
            or initial.get("role")
            or initial.get("expected_role")
            or initial.get("user_type")
            or initial.get("account_type")
            or initial.get("type")
        )
        if initial.get("is_midwife") is True or str(initial.get("is_midwife")).lower() == "true":
            raw_val = "MIDWIFE"

        if raw_val:
            normalized = User.Role.normalize(raw_val)
            # Privileged accounts must be provisioned by an existing admin;
            # public registration may create only patient or midwife accounts.
            if normalized in (User.Role.PATIENT, User.Role.MIDWIFE):
                return normalized
            if normalized == User.Role.ADMIN:
                raise serializers.ValidationError(
                    "Admin accounts cannot be created through public registration."
                )
        return User.Role.PATIENT

    def validate_email(self, value):
        if value:
            value = value.strip().lower()
            if User.objects.filter(email__iexact=value).exists():
                raise serializers.ValidationError("A user with this email already exists.")
        return value or None

    def validate_phone_number(self, value):
        if value:
            value = value.strip()
            if User.objects.filter(phone_number__iexact=value).exists():
                raise serializers.ValidationError("A user with this phone number already exists.")
        return value or None

    def validate_username(self, value):
        if value:
            value = value.strip()
            if User.objects.filter(username__iexact=value).exists():
                raise serializers.ValidationError("This username is already taken.")
        return value or None

    def validate(self, attrs):
        email = attrs.get("email")
        phone_number = attrs.get("phone_number")
        password = attrs.get("password")
        password_confirm = attrs.get("password_confirm")

        if not email and not phone_number:
            raise serializers.ValidationError(
                {"non_field_errors": ["Either Mobile Phone Number or Email Address is required."]}
            )

        # Validate password if provided
        if password or password_confirm:
            if password != password_confirm:
                raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
            if password:
                validate_password(password)

        return attrs

    # ---- Create ----

    def create(self, validated_data):
        first_name = validated_data.pop("first_name", "")
        last_name = validated_data.pop("last_name", "")
        date_of_birth = validated_data.pop("date_of_birth", None)
        gender = validated_data.pop("gender", Profile.Gender.FEMALE) or Profile.Gender.FEMALE
        region = validated_data.pop("region", "")
        validated_data.pop("otp_code", None)
        validated_data.pop("password_confirm", None)
        password = validated_data.pop("password", None)
        full_name = validated_data.pop("full_name", "")

        # Derive first_name and last_name from full_name if necessary
        if full_name and not (first_name or last_name):
            parts = full_name.strip().split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""

        # Auto-generate unique username if not provided
        username = validated_data.get("username")
        if not username:
            email = validated_data.get("email")
            phone = validated_data.get("phone_number")
            prefix = (email.split("@")[0] if email else phone or "user").replace("+", "").replace("-", "")
            base_username = prefix[:20]
            username = f"{base_username}_{uuid.uuid4().hex[:6]}"
            validated_data["username"] = username

        user = User(
            first_name=first_name,
            last_name=last_name,
            **validated_data
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()

        # Auto-create related records
        Profile.objects.create(
            user=user,
            first_name=first_name,
            last_name=last_name,
            date_of_birth=date_of_birth,
            gender=gender,
            region=region,
        )
        license_number = (self.initial_data.get("license_number") if hasattr(self, 'initial_data') and isinstance(self.initial_data, dict) else None)

        if user.role == User.Role.MIDWIFE:
            from apps.midwives.models import MidwifeProfile
            defaults = {
                "verification_status": MidwifeProfile.VerificationStatus.PENDING,
            }
            if license_number and str(license_number).strip():
                defaults["license_number"] = str(license_number).strip()

            MidwifeProfile.objects.get_or_create(
                user=user,
                # Keep the submitted licence number when supplied; otherwise
                # create a valid placeholder for the existing unique field.
                defaults={
                    **defaults,
                    "license_number": defaults.get(
                        "license_number", f"LIC-{uuid.uuid4().hex[:8].upper()}"
                    ),
                    "verification_status": MidwifeProfile.VerificationStatus.PENDING,
                    "is_accepting_bookings": False,
                }
            )

        return user


class UserRegistrationResponseSerializer(serializers.Serializer):
    """Shape of the 201 response after successful registration."""

    message = serializers.CharField()
    user = serializers.DictField()
    access = serializers.CharField()
    refresh = serializers.CharField()


# ---------------------------------------------------------------------------
# Login response (for Swagger docs only)
# ---------------------------------------------------------------------------

class LoginResponseSerializer(serializers.Serializer):
    access = serializers.CharField(help_text="Short-lived JWT access token.")
    refresh = serializers.CharField(help_text="Long-lived JWT refresh token.")
    user = serializers.DictField(help_text="Authenticated user summary.")


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField(help_text="The refresh token to blacklist.")


# ---------------------------------------------------------------------------
# OTP Serializers (Send & Verify)
# ---------------------------------------------------------------------------

class SendOTPSerializer(serializers.Serializer):
    phone_number_or_email = serializers.CharField(
        required=True, help_text="Mobile phone number or email address to receive OTP."
    )
    purpose = serializers.ChoiceField(
        choices=OTPVerification.Purpose.choices,
        default=OTPVerification.Purpose.REGISTRATION,
        help_text="Purpose of OTP.",
    )


class VerifyOTPSerializer(serializers.Serializer):
    phone_number_or_email = serializers.CharField(required=True)
    otp_code = serializers.CharField(max_length=6, required=True)
    purpose = serializers.ChoiceField(
        choices=OTPVerification.Purpose.choices,
        default=OTPVerification.Purpose.REGISTRATION,
    )


class OTPLoginSerializer(serializers.Serializer):
    phone_number_or_email = serializers.CharField(required=True, help_text="Mobile phone number or email address.")
    otp_code = serializers.CharField(max_length=6, required=True, help_text="Verified 6-digit OTP code.")
    role = serializers.CharField(required=False, write_only=True, help_text="Optional. Expected role for authentication (PATIENT or MIDWIFE).")
    expected_role = serializers.CharField(required=False, write_only=True, help_text="Optional. Alias for role.")


# ---------------------------------------------------------------------------
# Password Change (authenticated user)
# ---------------------------------------------------------------------------

class PasswordChangeSerializer(serializers.Serializer):
    old_password = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )
    new_password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
    )
    new_password_confirm = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "New passwords do not match."}
            )
        validate_password(attrs["new_password"])
        return attrs

    def validate_old_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value


# ---------------------------------------------------------------------------
# Password Reset (Email & OTP)
# ---------------------------------------------------------------------------

class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(help_text="Email address linked to your account.")

    def validate_email(self, value):
        return value.lower()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField(help_text="Base-64 encoded user ID from the reset link.")
    token = serializers.CharField(help_text="Password reset token from the reset link.")
    new_password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
    )
    new_password_confirm = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )

    def validate(self, attrs):
        if attrs["new_password"] != attrs["new_password_confirm"]:
            raise serializers.ValidationError(
                {"new_password_confirm": "Passwords do not match."}
            )

        try:
            uid = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"uid": "Invalid reset link."})

        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError({"token": "Reset link is invalid or has expired."})

        validate_password(attrs["new_password"], user=user)
        attrs["user"] = user
        return attrs


class PasswordResetOTPRequestSerializer(serializers.Serializer):
    phone_number_or_email = serializers.CharField(
        required=True, help_text="Registered mobile number or email address."
    )


class PasswordResetOTPConfirmSerializer(serializers.Serializer):
    phone_number_or_email = serializers.CharField(required=True)
    otp_code = serializers.CharField(max_length=6, required=True)
    new_password = serializers.CharField(
        write_only=True, min_length=8, style={"input_type": "password"}
    )
    new_password_confirm = serializers.CharField(
        write_only=True, style={"input_type": "password"}
    )

    def validate(self, attrs):
        if attrs["new_password"] != attrs.get("new_password_confirm"):
            raise serializers.ValidationError({"new_password_confirm": "Passwords do not match."})

        identifier = attrs["phone_number_or_email"].strip()

        user = User.objects.filter(
            email__iexact=identifier
        ).first() or User.objects.filter(
            phone_number__iexact=identifier
        ).first()

        if not user:
            raise serializers.ValidationError({"phone_number_or_email": "No account found matching this credential."})

        # Verify OTP record
        otp = OTPVerification.objects.filter(
            phone_number_or_email__iexact=identifier,
            otp_code=attrs["otp_code"],
            purpose=OTPVerification.Purpose.PASSWORD_RESET,
            expires_at__gt=timezone.now(),
        ).first()

        if not otp:
            raise serializers.ValidationError({"otp_code": "Invalid or expired OTP code."})

        validate_password(attrs["new_password"], user=user)
        attrs["user"] = user
        attrs["otp_record"] = otp
        return attrs
