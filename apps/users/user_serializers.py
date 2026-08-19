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
            from apps.midwives.serializers import MidwifeProfileSerializer
            return MidwifeProfileSerializer(obj.midwife_profile, context=self.context).data
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
