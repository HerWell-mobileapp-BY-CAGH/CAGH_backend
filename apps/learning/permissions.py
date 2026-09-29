"""Authorization rules for Learning Center editorial content."""

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.users.models import User


class IsAdminOrReadOnly(BasePermission):
    """Allow everyone to read public learning data, but only admins to edit it.

    The API uses the application's ``role`` field as well as Django's staff
    flag.  Supporting both keeps JWT-created application administrators and
    Django superusers equally able to manage Learning Center content.
    """

    message = "Only administrators can manage learning materials."

    def has_permission(self, request, view):
        # Reading remains available to the patient and midwife applications.
        if request.method in SAFE_METHODS:
            return True

        if not (request.user and request.user.is_authenticated):
            return False

        return request.user.is_staff or (
            User.Role.normalize(getattr(request.user, "role", None))
            == User.Role.ADMIN
        )
