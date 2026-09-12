"""
OpenAPI response serializers for admin portal endpoints.

These serializers document the response shape for Swagger/ReDoc; the views
build plain dict payloads via admin_services helpers.
"""

from django.db import transaction
from rest_framework import serializers

from apps.notifications.models import Notification
from apps.users.models import EmergencyContact, Profile, User
from apps.users.user_serializers import ProfileSerializer
from apps.midwives.models import Hospital
from apps.appointments.models import Appointment
from apps.appointments.serializers import AppointmentSerializer
from apps.consultations.models import Consultation
from apps.consultations.serializers import ConsultationSerializer


class AdminDashboardTotalsSerializer(serializers.Serializer):
    """Platform-wide count summary shown at the top of the admin dashboard."""

    users = serializers.IntegerField(help_text="Total registered user accounts.")
    midwives = serializers.IntegerField(help_text="Total midwife profile records.")
    consultations = serializers.IntegerField(help_text="Total consultation sessions.")
    appointments = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Appointment counts keyed by status (for example, PENDING).",
    )


class AdminRecentActivitySerializer(serializers.Serializer):
    """One row in the admin recent-activity feed (sourced from AuditLog)."""

    id = serializers.UUIDField()
    action = serializers.CharField()
    timestamp = serializers.DateTimeField()
    ip_address = serializers.IPAddressField(allow_null=True)
    details = serializers.DictField()
    performed_by = serializers.CharField(allow_null=True)


class AdminDashboardResponseSerializer(serializers.Serializer):
    """Full payload returned by GET /api/v1/admin/dashboard/."""

    totals = AdminDashboardTotalsSerializer()
    midwives_by_verification_status = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Midwife counts keyed by verification_status.",
    )
    consultations_by_status = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Consultation counts keyed by status.",
    )
    appointments_by_status = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Appointment counts keyed by status.",
    )
    recent_activities = AdminRecentActivitySerializer(many=True)


class AdminMidwifeSummarySerializer(serializers.Serializer):
    """Identity block for the selected midwife on the detail stats screen."""

    id = serializers.UUIDField()
    user_id = serializers.UUIDField()
    display_name = serializers.CharField()
    email = serializers.EmailField(allow_null=True)
    phone_number = serializers.CharField(allow_null=True)
    license_number = serializers.CharField()
    verification_status = serializers.CharField()
    specialty = serializers.CharField()
    hospital_name = serializers.CharField(allow_null=True)


class AdminMidwifeStatsResponseSerializer(serializers.Serializer):
    """Full payload returned by GET /api/v1/admin/midwives/{id}/stats/."""

    midwife = AdminMidwifeSummarySerializer()
    totals = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Total consultations and appointments for this midwife.",
    )
    consultations_by_status = serializers.DictField(child=serializers.IntegerField())
    appointments_by_status = serializers.DictField(child=serializers.IntegerField())
    recent_consultations = serializers.ListField(child=serializers.DictField())
    recent_appointments = serializers.ListField(child=serializers.DictField())


class AdminNotificationSerializer(serializers.ModelSerializer):
    """Serializer for notifications sent by an administrator to one user."""

    user_id = serializers.PrimaryKeyRelatedField(
        source="user", queryset=User.objects.all(), write_only=True
    )
    user = serializers.PrimaryKeyRelatedField(read_only=True)
    type = serializers.ChoiceField(choices=Notification.NotificationType.choices)

    class Meta:
        model = Notification
        fields = (
            "id", "user", "user_id", "title", "body", "type", "action",
            "reference_id", "is_read", "created_at",
        )
        read_only_fields = ("id", "user", "is_read", "created_at")


class AdminEmergencyContactSerializer(serializers.ModelSerializer):
    """Serializer for emergency contacts created on behalf of a user."""

    user_id = serializers.PrimaryKeyRelatedField(
        source="user", queryset=User.objects.all(), write_only=True
    )
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = EmergencyContact
        fields = ("id", "user", "user_id", "name", "relationship", "phone_number", "is_primary")
        read_only_fields = ("id", "user")


class AdminHospitalSerializer(serializers.ModelSerializer):
    """Hospital details plus the number of linked midwife profiles."""

    midwife_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Hospital
        fields = (
            "id", "name", "address", "phone", "latitude", "longitude",
            "created_at", "updated_at", "midwife_count",
        )
        read_only_fields = ("id", "created_at", "updated_at", "midwife_count")


class AdminLanguagePreferenceSerializer(serializers.ModelSerializer):
    """The signed-in administrator's language preference for the admin UI."""

    class Meta:
        model = Profile
        fields = ("preferred_language",)


class AdminProfileSerializer(serializers.ModelSerializer):
    """The authenticated administrator's account and editable profile data."""

    profile = ProfileSerializer(required=False)

    class Meta:
        model = User
        fields = (
            "id", "username", "email", "phone_number", "first_name", "last_name",
            "role", "profile",
        )
        read_only_fields = ("id", "role")

    def validate_email(self, value):
        value = value.strip().lower() if value else None
        if value and User.objects.filter(email__iexact=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

    def validate_phone_number(self, value):
        value = value.strip() if value else None
        if value and User.objects.filter(phone_number=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("A user with this phone number already exists.")
        return value

    def validate_username(self, value):
        value = value.strip() if value else None
        if value and User.objects.filter(username__iexact=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError("This username is already taken.")
        return value

    @transaction.atomic
    def update(self, instance, validated_data):
        profile_data = validated_data.pop("profile", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()

        if profile_data is not None:
            profile, _ = Profile.objects.get_or_create(user=instance)
            for field, value in profile_data.items():
                setattr(profile, field, value)
            profile.save()
        return instance


class AdminAppointmentSerializer(AppointmentSerializer):
    """Complete appointment record for the administrator portal."""

    class Meta(AppointmentSerializer.Meta):
        model = Appointment


class AdminConsultationSerializer(ConsultationSerializer):
    """Complete consultation record for the administrator portal."""

    class Meta(ConsultationSerializer.Meta):
        model = Consultation
