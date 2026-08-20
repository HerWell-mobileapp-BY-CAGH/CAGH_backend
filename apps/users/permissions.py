from rest_framework import permissions
from django.contrib.auth import get_user_model

User = get_user_model()


class IsPatient(permissions.BasePermission):
    """
    Allows access only to authenticated users with role PATIENT (or ADMIN / staff).
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        user_role = User.Role.normalize(getattr(request.user, "role", None))
        return (
            request.user.is_staff
            or user_role == User.Role.ADMIN
            or user_role == User.Role.PATIENT
        )


class IsMidwife(permissions.BasePermission):
    """
    Allows access only to authenticated users with role MIDWIFE (or ADMIN / staff).
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        user_role = User.Role.normalize(getattr(request.user, "role", None))
        return (
            request.user.is_staff
            or user_role == User.Role.ADMIN
            or user_role == User.Role.MIDWIFE
        )


class IsAdmin(permissions.BasePermission):
    """
    Allows access only to authenticated users with role ADMIN or staff.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        user_role = User.Role.normalize(getattr(request.user, "role", None))
        return (
            request.user.is_staff
            or user_role == User.Role.ADMIN
        )


class IsVerifiedMidwife(permissions.BasePermission):
    """
    Allows access only to authenticated MIDWIFE users whose MidwifeProfile
    verification_status is APPROVED (or ADMIN / staff).
    Returns False (403) for operational midwife endpoints if verification is PENDING, REJECTED, or SUSPENDED.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_staff or getattr(request.user, "role", None) == User.Role.ADMIN:
            return True

        user_role = User.Role.normalize(getattr(request.user, "role", None))
        if user_role != User.Role.MIDWIFE:
            return False

        profile = getattr(request.user, "midwife_profile", None)
        if not profile:
            return False

        from apps.midwives.models import MidwifeProfile
        return profile.verification_status == MidwifeProfile.VerificationStatus.APPROVED
