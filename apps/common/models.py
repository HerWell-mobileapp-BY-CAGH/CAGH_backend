import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

class Facility(models.Model):
    class FacilityType(models.TextChoices):
        HOSPITAL = 'HOSPITAL', _('Hospital')
        HEALTH_CENTER = 'HEALTH_CENTER', _('Health Center')
        CLINIC = 'CLINIC', _('Clinic')
        PHARMACY = 'PHARMACY', _('Pharmacy')
        LABORATORY = 'LABORATORY', _('Laboratory')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    facility_type = models.CharField(
        max_length=50,
        choices=FacilityType.choices,
        default=FacilityType.HOSPITAL,
        db_index=True
    )
    address = models.TextField()
    city = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)
    phone_number = models.CharField(max_length=30, blank=True)
    operating_hours = models.CharField(
        max_length=200,
        default="Mon-Fri: 8:00 AM - 6:00 PM, 24/7 Emergency"
    )
    available_services = models.JSONField(default=list, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    rating_average = models.DecimalField(max_digits=3, decimal_places=2, null=True, blank=True, default=None, help_text="Average rating score out of 5.0 (Null if unrated)")
    image = models.ImageField(upload_to='facilities/', blank=True, null=True, help_text="Facility photo image file")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)


    class Meta:
        verbose_name_plural = 'Facilities'
        ordering = ['name']
        indexes = [
            models.Index(fields=['is_active', 'facility_type']),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_facility_type_display()})"



class AuditLog(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(default=dict, blank=True)

    def __str__(self):
        actor = self.user.username if self.user else "System"
        return f"[{self.timestamp}] {actor}: {self.action}"


class Report(models.Model):
    class ReportStatus(models.TextChoices):
        OPEN = 'OPEN', _('Open')
        INVESTIGATING = 'INVESTIGATING', _('Investigating')
        RESOLVED = 'RESOLVED', _('Resolved')
        DISMISSED = 'DISMISSED', _('Dismissed')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='filed_reports')
    reported_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reports_against'
    )
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=ReportStatus.choices, default=ReportStatus.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report {self.id} by {self.reporter.username} ({self.status})"
