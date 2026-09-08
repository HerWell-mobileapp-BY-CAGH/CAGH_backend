"""
User-domain serializers (non-auth).

Kept separate from auth serializers to avoid circular imports
(auth serializers → models only; views import from both).
"""

import uuid

from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from .models import User, Profile, EmergencyContact, SOSLog, UserPreference


class UserPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserPreference
        fields = ("push_notifications", "email_notifications", "dark_mode")
        read_only_fields = ()


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = (
            "id",
            "first_name",
            "last_name",
            "gender",
            "date_of_birth",
            "profile_image",
            "region",
            "city",
            "preferred_language",
            "emergency_contact_visibility",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")


class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    preferences = UserPreferenceSerializer(read_only=True)
    midwife_profile = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "role",
            "phone_number",
            "profile",
            "preferences",
            "midwife_profile",
        )
        read_only_fields = ("id", "role")
        extra_kwargs = {
            "username": {"required": False, "allow_null": True, "allow_blank": True},
            "email": {"required": False, "allow_null": True, "allow_blank": True},
        }

    def get_midwife_profile(self, obj):
        if hasattr(obj, 'midwife_profile'):
            mw = obj.midwife_profile
            return {
                "id": str(mw.id),
                "license_number": mw.license_number,
                "verification_status": mw.verification_status,
                "rejection_reason": mw.rejection_reason,
                "suspension_reason": mw.suspension_reason,
                "specialty": mw.specialty,
                "consultation_fee": str(mw.consultation_fee),
                "experience_years": mw.experience_years,
                "is_accepting_bookings": mw.is_accepting_bookings,
                "hospital_id": str(mw.hospital.id) if mw.hospital else None,
                "hospital_name": mw.hospital.name if mw.hospital else None,
            }
        return None


class AdminUserCreateSerializer(serializers.ModelSerializer):
    """Create users from the protected administrator API."""

    username = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone_number = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=20)
    password = serializers.CharField(write_only=True, min_length=8, style={"input_type": "password"})
    password_confirm = serializers.CharField(write_only=True, style={"input_type": "password"})
    full_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    first_name = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=100)
    last_name = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=100)
    date_of_birth = serializers.DateField(write_only=True, required=False, allow_null=True)
    gender = serializers.ChoiceField(
        choices=Profile.Gender.choices, write_only=True, required=False, allow_null=True, allow_blank=True
    )
    region = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=100)

    class Meta:
        model = User
        fields = (
            "username", "email", "phone_number", "password", "password_confirm", "role",
            "full_name", "first_name", "last_name", "date_of_birth", "gender", "region",
        )

    def validate_email(self, value):
        value = value.strip().lower() if value else None
        if value and User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_phone_number(self, value):
        value = value.strip() if value else None
        if value and User.objects.filter(phone_number__iexact=value).exists():
            raise serializers.ValidationError("A user with this phone number already exists.")
        return value

    def validate_username(self, value):
        value = value.strip() if value else None
        if value and User.objects.filter(username__iexact=value).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("phone_number"):
            raise serializers.ValidationError(
                {"non_field_errors": ["Either Mobile Phone Number or Email Address is required."]}
            )
        if attrs["password"] != attrs["password_confirm"]:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        validate_password(attrs["password"])
        return attrs

    def create(self, validated_data):
        password = validated_data.pop("password")
        validated_data.pop("password_confirm")
        full_name = validated_data.pop("full_name", "")
        first_name = validated_data.pop("first_name", "")
        last_name = validated_data.pop("last_name", "")
        date_of_birth = validated_data.pop("date_of_birth", None)
        gender = validated_data.pop("gender", Profile.Gender.FEMALE) or Profile.Gender.FEMALE
        region = validated_data.pop("region", "")

        if full_name and not (first_name or last_name):
            parts = full_name.strip().split(" ", 1)
            first_name, last_name = parts[0], parts[1] if len(parts) > 1 else ""

        if not validated_data.get("username"):
            identifier = validated_data.get("email") or validated_data.get("phone_number") or "user"
            prefix = identifier.split("@", 1)[0].replace("+", "").replace("-", "")[:20]
            validated_data["username"] = f"{prefix}_{uuid.uuid4().hex[:6]}"

        if validated_data.get("role") == User.Role.ADMIN:
            # Keep domain role and Django admin access aligned for provisioned admins.
            validated_data["is_staff"] = True

        user = User(**validated_data)
        user.set_password(password)
        user.save()
        Profile.objects.create(
            user=user,
            first_name=first_name,
            last_name=last_name,
            date_of_birth=date_of_birth,
            gender=gender,
            region=region,
        )
        UserPreference.objects.create(user=user)

        if user.role == User.Role.MIDWIFE:
            from apps.midwives.models import MidwifeProfile

            MidwifeProfile.objects.get_or_create(
                user=user,
                defaults={
                    "license_number": f"LIC-{uuid.uuid4().hex[:8].upper()}",
                    "verification_status": MidwifeProfile.VerificationStatus.PENDING,
                    "is_accepting_bookings": False,
                },
            )
        return user



class EmergencyContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmergencyContact
        fields = ("id", "name", "relationship", "phone_number", "is_primary")
        read_only_fields = ("id",)


class SOSLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = SOSLog
        fields = ("id", "latitude", "longitude", "status", "triggered_at")
        read_only_fields = ("id", "triggered_at")
