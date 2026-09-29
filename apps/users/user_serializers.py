"""
User-domain serializers (non-auth).

Kept separate from auth serializers to avoid circular imports
(auth serializers → models only; views import from both).
"""

import secrets
import uuid

from django.contrib.auth.password_validation import validate_password
from django.db import transaction
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
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    profile = ProfileSerializer(read_only=True)
    preferences = UserPreferenceSerializer(read_only=True)
    midwife_profile = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "first_name",
            "last_name",
            "username",
            "email",
            "role",
            "phone_number",
            "must_change_password",
            "profile",
            "preferences",
            "midwife_profile",
        )
        read_only_fields = ("id", "role", "must_change_password")
        extra_kwargs = {
            "username": {"required": False, "allow_null": True, "allow_blank": True},
            "email": {"required": False, "allow_null": True, "allow_blank": True},
        }

    def get_midwife_profile(self, obj):
        if getattr(obj, 'role', '') != 'MIDWIFE':
            return None
        try:
            mw = getattr(obj, 'midwife_profile', None)
            if mw:
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
                    "hospital_id": str(mw.hospital_id) if mw.hospital_id else None,
                    "hospital_name": mw.hospital.name if mw.hospital else None,
                }
        except Exception:
            pass
        return None


class AdminUserCreateSerializer(serializers.ModelSerializer):
    """Create users from the protected administrator API."""

    username = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True, allow_null=True)
    phone_number = serializers.CharField(required=False, allow_blank=True, allow_null=True, max_length=20)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, min_length=8, style={"input_type": "password"})
    password_confirm = serializers.CharField(write_only=True, required=False, allow_blank=True, style={"input_type": "password"})
    generate_temporary_password = serializers.BooleanField(write_only=True, required=False, default=False)
    full_name = serializers.CharField(write_only=True, required=False, allow_blank=True)
    first_name = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=100)
    last_name = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=100)
    date_of_birth = serializers.DateField(write_only=True, required=False, allow_null=True)
    gender = serializers.ChoiceField(
        choices=Profile.Gender.choices, write_only=True, required=False, allow_null=True, allow_blank=True
    )
    region = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=100)
    # These fields let an administrator provision a complete midwife profile.
    license_number = serializers.CharField(write_only=True, required=False, allow_blank=True, allow_null=True, max_length=100)
    cv_file = serializers.FileField(write_only=True, required=False, allow_null=True)
    hospital_id = serializers.UUIDField(write_only=True, required=False, allow_null=True)
    bio = serializers.CharField(write_only=True, required=False, allow_blank=True)
    experience_years = serializers.IntegerField(write_only=True, required=False, min_value=0)
    specialty = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=150)
    languages = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=200)

    class Meta:
        model = User
        fields = (
            "username", "email", "phone_number", "password", "password_confirm", "generate_temporary_password", "role",
            "full_name", "first_name", "last_name", "date_of_birth", "gender", "region",
            "license_number", "cv_file", "hospital_id", "bio", "experience_years", "specialty", "languages",
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

    def validate_license_number(self, value):
        value = value.strip() if value else value
        if value and self.initial_data.get("role") == User.Role.MIDWIFE:
            from apps.midwives.models import MidwifeProfile
            if MidwifeProfile.objects.filter(license_number=value).exists():
                raise serializers.ValidationError("A midwife with this license number already exists.")
        return value

    def validate(self, attrs):
        if not attrs.get("email") and not attrs.get("phone_number"):
            raise serializers.ValidationError(
                {"non_field_errors": ["Either Mobile Phone Number or Email Address is required."]}
            )
        generate_temporary_password = attrs.get("generate_temporary_password", False)
        password = attrs.get("password", "")
        password_confirm = attrs.get("password_confirm", "")
        if not password and not generate_temporary_password:
            raise serializers.ValidationError({"password": "Provide a password or set generate_temporary_password to true."})
        if password and password != password_confirm:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        if password:
            validate_password(password)

        professional_fields = {"license_number", "cv_file", "hospital_id", "bio", "experience_years", "specialty", "languages"}
        if professional_fields.intersection(attrs) and attrs.get("role") != User.Role.MIDWIFE:
            raise serializers.ValidationError("Midwife professional fields can only be used when role is MIDWIFE.")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop("password", "")
        validated_data.pop("password_confirm", None)
        generate_temporary_password = validated_data.pop("generate_temporary_password", False)
        self.temporary_password = None
        if generate_temporary_password:
            # Returned only once to the authenticated administrator who created it.
            self.temporary_password = secrets.token_urlsafe(12)
            password = self.temporary_password
        full_name = validated_data.pop("full_name", "")
        first_name = validated_data.pop("first_name", "")
        last_name = validated_data.pop("last_name", "")
        date_of_birth = validated_data.pop("date_of_birth", None)
        gender = validated_data.pop("gender", Profile.Gender.FEMALE) or Profile.Gender.FEMALE
        region = validated_data.pop("region", "")
        midwife_fields = {key: validated_data.pop(key, None) for key in (
            "license_number", "cv_file", "hospital_id", "bio", "experience_years", "specialty", "languages"
        )}

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

        hospital = None
        if validated_data.get("role") == User.Role.MIDWIFE:
            # Resolve the foreign key before creating the user, preventing a
            # partially provisioned account for an invalid hospital UUID.
            from apps.midwives.models import Hospital
            hospital_id = midwife_fields.pop("hospital_id")
            if hospital_id:
                try:
                    hospital = Hospital.objects.get(pk=hospital_id)
                except Hospital.DoesNotExist:
                    raise serializers.ValidationError({"hospital_id": "Hospital not found."})

        user = User(**validated_data)
        user.set_password(password)
        user.must_change_password = bool(self.temporary_password)
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
                    "license_number": midwife_fields["license_number"] or f"LIC-{uuid.uuid4().hex[:8].upper()}",
                    "cv_file": midwife_fields["cv_file"],
                    "hospital": hospital,
                    "bio": midwife_fields["bio"] or "",
                    "experience_years": midwife_fields["experience_years"] if midwife_fields["experience_years"] is not None else 0,
                    "specialty": midwife_fields["specialty"] or "Maternal Health Specialist",
                    "languages": midwife_fields["languages"] or "English, Amharic",
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
