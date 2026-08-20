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
        return (
            request.user.is_staff
            or getattr(request.user, "role", None) == User.Role.ADMIN
            or getattr(request.user, "role", None) == User.Role.PATIENT
        )


class IsMidwife(permissions.BasePermission):
    """
    Allows access only to authenticated users with role MIDWIFE (or ADMIN / staff).
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return (
            request.user.is_staff
            or getattr(request.user, "role", None) == User.Role.ADMIN
            or getattr(request.user, "role", None) == User.Role.MIDWIFE
        )


class IsAdmin(permissions.BasePermission):
    """
    Allows access only to authenticated users with role ADMIN or staff.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        return (
            request.user.is_staff
            or getattr(request.user, "role", None) == User.Role.ADMIN
        )
