"""
Admin dashboard aggregation helpers.

These functions centralise the counting/query logic used by the admin portal
API so views stay thin and the React dashboard can consume one stable payload.
"""

from django.contrib.auth import get_user_model
from django.db.models import Count

from apps.appointments.models import Appointment
from apps.consultations.models import Consultation
from apps.common.models import AuditLog
from apps.midwives.models import MidwifeProfile

User = get_user_model()

# Default number of recent audit-log rows returned on the dashboard feed.
DEFAULT_RECENT_ACTIVITY_LIMIT = 15

# Default number of recent consultation/appointment rows on the midwife detail view.
DEFAULT_MIDWIFE_RECENT_LIMIT = 10


def _counts_by_status(queryset, status_field: str) -> dict[str, int]:
    """
    Build a {STATUS: count} dictionary from a queryset grouped by status.

    Every known status for the model is included (even when count is 0) so the
    frontend can render consistent charts without guessing missing keys.
    """
    grouped = (
        queryset.values(status_field)
        .annotate(count=Count("id"))
        .order_by(status_field)
    )
    counts = {row[status_field]: row["count"] for row in grouped}
    return counts


def build_admin_dashboard_payload(*, recent_activity_limit: int = DEFAULT_RECENT_ACTIVITY_LIMIT) -> dict:
    """
    Compose the full admin dashboard statistics payload.

    Returns platform-wide totals, breakdowns by status, midwife verification
    counts, and the most recent audit-log entries for the activity feed.
    """
    # --- User totals ---------------------------------------------------------
    total_users = User.objects.count()
    # Use profile rows because appointments and consultations point to a profile,
    # rather than directly to a user account.
    total_midwives = MidwifeProfile.objects.count()

    # --- Midwife verification breakdown --------------------------------------
    midwives_by_status = _counts_by_status(
        MidwifeProfile.objects.all(),
        "verification_status",
    )
    # Ensure every verification state appears in the response for charting.
    for status_value, _ in MidwifeProfile.VerificationStatus.choices:
        midwives_by_status.setdefault(status_value, 0)

    # --- Consultation totals -------------------------------------------------
    total_consultations = Consultation.objects.count()
    consultations_by_status = _counts_by_status(
        Consultation.objects.all(),
        "status",
    )
    for status_value, _ in Consultation.ConsultationStatus.choices:
        consultations_by_status.setdefault(status_value, 0)

    # --- Appointment totals --------------------------------------------------
    appointments_by_status = _counts_by_status(
        Appointment.objects.all(),
        "status",
    )
    for status_value, _ in Appointment.AppointmentStatus.choices:
        appointments_by_status.setdefault(status_value, 0)

    # --- Recent admin/system activity (newest first) -------------------------
    recent_logs = (
        AuditLog.objects.select_related("user")
        .order_by("-timestamp")[:recent_activity_limit]
    )
    recent_activities = [
        {
            "id": str(log.id),
            "action": log.action,
            "timestamp": log.timestamp.isoformat(),
            "ip_address": log.ip_address,
            "details": log.details,
            "performed_by": _audit_actor_label(log),
        }
        for log in recent_logs
    ]

    return {
        "totals": {
            "users": total_users,
            "midwives": total_midwives,
            "consultations": total_consultations,
            # Keep the appointment status breakdown beside the other headline
            # totals, matching the single dashboard payload consumed by admin UI.
            "appointments": appointments_by_status,
        },
        "midwives_by_verification_status": midwives_by_status,
        "consultations_by_status": consultations_by_status,
        "appointments_by_status": appointments_by_status,
        "recent_activities": recent_activities,
    }


def build_midwife_stats_payload(
    midwife_profile: MidwifeProfile,
    *,
    recent_limit: int = DEFAULT_MIDWIFE_RECENT_LIMIT,
) -> dict:
    """
    Build consultation and appointment statistics for a single midwife profile.

    Used when an admin selects one midwife in the dashboard and needs per-status
    counts plus the most recent related records.
    """
    user = midwife_profile.user
    profile = getattr(user, "profile", None)
    display_name = ""
    if profile and (profile.first_name or profile.last_name):
        display_name = f"{profile.first_name} {profile.last_name}".strip()
    if not display_name:
        display_name = user.username or user.email or str(user.id)

    # Scope all metrics to this midwife's profile foreign key.
    consultation_qs = Consultation.objects.filter(midwife=midwife_profile)
    appointment_qs = Appointment.objects.filter(midwife=midwife_profile)

    consultations_by_status = _counts_by_status(consultation_qs, "status")
    for status_value, _ in Consultation.ConsultationStatus.choices:
        consultations_by_status.setdefault(status_value, 0)

    appointments_by_status = _counts_by_status(appointment_qs, "status")
    for status_value, _ in Appointment.AppointmentStatus.choices:
        appointments_by_status.setdefault(status_value, 0)

    # Recent rows give the admin a quick timeline without loading full lists.
    recent_consultations = list(
        consultation_qs.select_related("user", "appointment")
        .order_by("-created_at")[:recent_limit]
        .values(
            "id",
            "status",
            "consultation_type",
            "created_at",
            "started_at",
            "ended_at",
            "user__email",
            "user__username",
            "appointment__appointment_number",
        )
    )
    recent_appointments = list(
        appointment_qs.select_related("user")
        .order_by("-created_at")[:recent_limit]
        .values(
            "id",
            "appointment_number",
            "status",
            "appointment_type",
            "scheduled_date",
            "start_time",
            "end_time",
            "fee",
            "created_at",
            "user__email",
            "user__username",
        )
    )

    return {
        "midwife": {
            "id": str(midwife_profile.id),
            "user_id": str(user.id),
            "display_name": display_name,
            "email": user.email,
            "phone_number": user.phone_number,
            "license_number": midwife_profile.license_number,
            "verification_status": midwife_profile.verification_status,
            "specialty": midwife_profile.specialty,
            "hospital_name": midwife_profile.hospital.name if midwife_profile.hospital else None,
        },
        "totals": {
            "consultations": consultation_qs.count(),
            "appointments": appointment_qs.count(),
        },
        "consultations_by_status": consultations_by_status,
        "appointments_by_status": appointments_by_status,
        "recent_consultations": recent_consultations,
        "recent_appointments": recent_appointments,
    }


def _audit_actor_label(log: AuditLog) -> str | None:
    """Return a human-readable label for who performed an audited action."""
    if not log.user:
        return None
    profile = getattr(log.user, "profile", None)
    if profile and (profile.first_name or profile.last_name):
        return f"{profile.first_name} {profile.last_name}".strip()
    return log.user.username or log.user.email
