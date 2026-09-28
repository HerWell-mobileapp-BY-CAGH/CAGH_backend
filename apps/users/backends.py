"""
Custom Authentication Backend for CAGH.

Allows users to authenticate via:
1. Email address (case-insensitive)
2. Mobile phone number
3. Username
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrPhoneBackend(ModelBackend):
    """
    Authenticate using email, mobile phone number, or username.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        User = get_user_model()

        if username is None:
            username = kwargs.get("email") or kwargs.get("phone_number") or kwargs.get("login")

        if not username:
            return None

        identifier = str(username).strip()

        try:
            user = User.objects.select_related(
                'profile', 'preferences', 'midwife_profile', 'midwife_profile__hospital'
            ).filter(
                Q(email__iexact=identifier) |
                Q(phone_number__iexact=identifier) |
                Q(username__iexact=identifier)
            ).first()
        except Exception:
            return None

        if user and self.user_can_authenticate(user):
            if password and user.check_password(password):
                return user
            if kwargs.get("otp_verified") is True:
                return user

        return None




