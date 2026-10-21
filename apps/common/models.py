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


class TranslationVersion(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    language = models.CharField(max_length=10, unique=True, db_index=True)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['language']

    def __str__(self):
        return f"{self.language}: v{self.version} ({self.updated_at.strftime('%Y-%m-%d %H:%M')})"

    @classmethod
    def get_version(cls, language: str) -> int:
        entry, _ = cls.objects.get_or_create(language=language.lower())
        return entry.version

    @classmethod
    def bump(cls, language: str):
        entry, _ = cls.objects.get_or_create(language=language.lower())
        entry.version += 1
        entry.save()


class TranslationKey(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text=_("Unique identifier for this string, matching Flutter ARB key e.g. 'welcomeBack', 'login'")
    )
    default_text = models.TextField(help_text=_("Default English source string"))
    category = models.CharField(
        max_length=100,
        blank=True,
        default="general",
        db_index=True,
        help_text=_("Logical module or category, e.g. 'auth', 'home', 'consultations', 'profile'")
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Translator notes or contextual description")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'key']
        indexes = [
            models.Index(fields=['category', 'key']),
        ]

    def __str__(self):
        return f"{self.key} ({self.category})"


class TranslationValue(models.Model):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        IN_REVIEW = 'IN_REVIEW', _('In Review')
        PUBLISHED = 'PUBLISHED', _('Published')
        ARCHIVED = 'ARCHIVED', _('Archived')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.ForeignKey(
        TranslationKey,
        on_delete=models.CASCADE,
        related_name='translations'
    )
    language = models.CharField(
        max_length=10,
        db_index=True,
        help_text=_("ISO language code e.g. 'en', 'am'")
    )
    value = models.TextField(help_text=_("Localized translated text"))
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PUBLISHED,
        db_index=True
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_translations'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['key', 'language']
        unique_together = ('key', 'language')
        indexes = [
            models.Index(fields=['language', 'status']),
        ]

    def __str__(self):
        return f"{self.key.key} [{self.language}]: {self.status}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.status == self.Status.PUBLISHED:
            TranslationVersion.bump(self.language)

    def delete(self, *args, **kwargs):
        lang = self.language
        was_published = self.status == self.Status.PUBLISHED
        super().delete(*args, **kwargs)
        if was_published:
            TranslationVersion.bump(lang)

