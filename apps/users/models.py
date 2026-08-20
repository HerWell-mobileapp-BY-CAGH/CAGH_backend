import uuid
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    class Role(models.TextChoices):
        PATIENT = 'PATIENT', _('Patient')
        MIDWIFE = 'MIDWIFE', _('Midwife')
        ADMIN = 'ADMIN', _('Admin')

        @classmethod
        def normalize(cls, role_val):
            if not role_val:
                return None
            r = str(role_val).upper().strip()
            if r in ('USER', 'PATIENT', 'PATIENTS', 'CLIENT'):
                return cls.PATIENT
            if r in ('MIDWIFE', 'MIDWIVES', 'NURSE', 'DOCTOR'):
                return cls.MIDWIFE
            if r in ('ADMIN', 'SUPERADMIN', 'STAFF'):
                return cls.ADMIN
            return r

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=150, unique=True, null=True, blank=True)
    email = models.EmailField(_('email address'), unique=True, null=True, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.PATIENT)
    phone_number = models.CharField(max_length=20, unique=True, null=True, blank=True)

    def __str__(self):
        identifier = self.email or self.phone_number or self.username or str(self.id)
        return f"{identifier} ({self.role})"


class Profile(models.Model):
    class Gender(models.TextChoices):
        FEMALE = 'FEMALE', _('Female')
        MALE = 'MALE', _('Male')
        OTHER = 'OTHER', _('Other')
        PREFER_NOT_TO_SAY = 'PREFER_NOT_TO_SAY', _('Prefer not to say')

    class Language(models.TextChoices):
        ENGLISH = 'en', _('English')
        AMHARIC = 'am', _('Amharic')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    gender = models.CharField(max_length=20, choices=Gender.choices, default=Gender.FEMALE)
    date_of_birth = models.DateField(null=True, blank=True)
    profile_image = models.ImageField(upload_to='profiles/', blank=True, null=True)
    region = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    preferred_language = models.CharField(max_length=10, choices=Language.choices, default=Language.ENGLISH)

    emergency_contact_visibility = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile for {self.first_name} {self.last_name}".strip() or f"Profile for {self.user}"


class OTPVerification(models.Model):
    class Purpose(models.TextChoices):
        REGISTRATION = 'REGISTRATION', _('Registration')
        LOGIN = 'LOGIN', _('Login')
        PASSWORD_RESET = 'PASSWORD_RESET', _('Password Reset')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number_or_email = models.CharField(max_length=100)
    otp_code = models.CharField(max_length=6)
    purpose = models.CharField(max_length=20, choices=Purpose.choices, default=Purpose.REGISTRATION)
    is_verified = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"OTP for {self.phone_number_or_email} ({self.purpose}) - Verified: {self.is_verified}"


class EmergencyContact(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='emergency_contacts')
    name = models.CharField(max_length=150)
    relationship = models.CharField(max_length=50)
    phone_number = models.CharField(max_length=20)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ['-is_primary', 'name']

    def __str__(self):
        return f"{self.name} ({self.relationship}) - {self.user.username}"


class SOSLog(models.Model):
    class SOSStatus(models.TextChoices):
        TRIGGERED = 'TRIGGERED', _('Triggered')
        RESOLVED = 'RESOLVED', _('Resolved')
        CANCELLED = 'CANCELLED', _('Cancelled')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sos_logs')
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    status = models.CharField(max_length=20, choices=SOSStatus.choices, default=SOSStatus.TRIGGERED)
    triggered_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-triggered_at']

    def __str__(self):
        return f"SOS by {self.user.username} at {self.triggered_at}"



class UserPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='preferences')
    push_notifications = models.BooleanField(default=True)
    email_notifications = models.BooleanField(default=True)
    dark_mode = models.BooleanField(default=False)

    def __str__(self):
        return f"Preferences for {self.user.username}"
