"""Shared helpers for midwife verification and access control."""

from django.contrib.auth import get_user_model

User = get_user_model()


def is_midwife_account(user) -> bool:
    """True when the user is a midwife account (by role or linked profile)."""
    if not user or not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff or User.Role.normalize(getattr(user, "role", None)) == User.Role.ADMIN:
        return False
    if User.Role.normalize(getattr(user, "role", None)) == User.Role.MIDWIFE:
        return True
    return hasattr(user, "midwife_profile")


def get_midwife_status_message(user) -> str | None:
    """
    Return a non-blocking status message for midwives who are not APPROVED.
    Used by clients to show pending/rejected/suspended notices after login.
    Does not prevent authentication or general API access.
    """
    if not is_midwife_account(user):
        return None

    profile = getattr(user, "midwife_profile", None)
    if not profile:
        return (
            "Your midwife profile is incomplete. Please complete your registration. "
            "You will not appear to patients until an admin approves your application."
        )

    from apps.midwives.models import MidwifeProfile

    status = profile.verification_status

    if status == MidwifeProfile.VerificationStatus.APPROVED:
        return None

    if status == MidwifeProfile.VerificationStatus.REJECTED:
        reason = (profile.rejection_reason or "").strip()
        if reason:
            return f"Your midwife application was rejected. Reason: {reason}"
        return "Your midwife application was rejected. Please contact support for details."

    if status == MidwifeProfile.VerificationStatus.SUSPENDED:
        reason = (profile.suspension_reason or "").strip()
        if reason:
            return f"Your midwife account has been suspended. Reason: {reason}"
        return "Your midwife account has been suspended. Please contact support."

    if status == MidwifeProfile.VerificationStatus.UNDER_REVIEW:
        return (
            "Your midwife application is under review. "
            "You can use the app, but you will not appear to patients or accept bookings until approved."
        )

    return (
        "Your midwife account is pending admin approval. "
        "You can use the app, but you will not appear to patients or accept bookings until approved."
    )


# Backwards-compatible alias (no longer used to block login/API access).
get_midwife_verification_block_message = get_midwife_status_message


def notify_midwife_review_result(
    midwife_profile,
    *,
    approved: bool = False,
    rejected: bool = False,
    suspended: bool = False,
    reason: str = "",
) -> None:
    """Create an in-app notification when an admin reviews a midwife application."""
    from apps.notifications.models import Notification

    user = midwife_profile.user
    if approved:
        title = "Midwife Application Approved"
        body = (
            "Congratulations! Your midwife account has been approved. "
            "You can now appear to patients and start accepting bookings."
        )
    elif suspended:
        title = "Midwife Account Suspended"
        body = reason.strip() or "Your midwife account has been suspended. Please contact support for more information."
    else:
        title = "Midwife Application Rejected"
        body = reason.strip() or "Your midwife application was not approved. Please contact support for more information."

    Notification.objects.create(
        user=user,
        title=title,
        body=body,
        type="SYSTEM",
        action="MIDWIFE_REVIEW",
        reference_id=str(midwife_profile.id),
    )
