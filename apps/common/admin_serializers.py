"""
OpenAPI response serializers for admin portal endpoints.

These serializers document the response shape for Swagger/ReDoc; the views
build plain dict payloads via admin_services helpers.
"""

from rest_framework import serializers


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
