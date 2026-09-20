"""
User-domain serializers (non-auth).

Kept separate from auth serializers to avoid circular imports
(auth serializers → models only; views import from both).
"""

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
        if getattr(obj, 'role', '') != 'MIDWIFE':
            return None
        try:
            mw = getattr(obj, 'midwife_profile', None)
            if mw:
                return {
                    "id": str(mw.id),
                    "license_number": mw.license_number,
                    "verification_status": mw.verification_status,
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
