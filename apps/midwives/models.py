import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class Hospital(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    address = models.TextField()
    phone = models.CharField(max_length=20)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class MidwifeProfile(models.Model):
    class VerificationStatus(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        UNDER_REVIEW = 'UNDER_REVIEW', _('Under Review')
        APPROVED = 'APPROVED', _('Approved')
        REJECTED = 'REJECTED', _('Rejected')
        SUSPENDED = 'SUSPENDED', _('Suspended')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='midwife_profile')
    hospital = models.ForeignKey(Hospital, on_delete=models.SET_NULL, null=True, blank=True, related_name='midwives')
    license_number = models.CharField(max_length=100, unique=True)
    bio = models.TextField(blank=True)
    experience_years = models.PositiveIntegerField(default=0)
    verification_status = models.CharField(
        max_length=20,
        choices=VerificationStatus.choices,
        default=VerificationStatus.PENDING
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_midwives'
    )
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Midwife {self.user.username} - {self.verification_status}"


class Qualification(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    midwife = models.ForeignKey(MidwifeProfile, on_delete=models.CASCADE, related_name='qualifications')
    title = models.CharField(max_length=200)
    institution = models.CharField(max_length=200)
    year_obtained = models.PositiveIntegerField()

    def __str__(self):
        return f"{self.title} - {self.institution}"


class Certificate(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    midwife = models.ForeignKey(MidwifeProfile, on_delete=models.CASCADE, related_name='certificates')
    title = models.CharField(max_length=200)
    document_url = models.URLField(max_length=500)
    is_verified = models.BooleanField(default=False)

    def __str__(self):
        return f"Cert: {self.title}"


class Expertise(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    midwives = models.ManyToManyField(MidwifeProfile, related_name='expertises', blank=True)

    def __str__(self):
        return self.name


class SavedMidwife(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_midwives')
    midwife = models.ForeignKey(MidwifeProfile, on_delete=models.CASCADE, related_name='saved_by_users')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'midwife')

    def __str__(self):
        return f"{self.user.username} saved {self.midwife.user.username}"
