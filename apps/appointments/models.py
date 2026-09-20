import uuid
from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from apps.midwives.models import MidwifeProfile


class Availability(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    midwife = models.ForeignKey(MidwifeProfile, on_delete=models.CASCADE, related_name='availabilities')
    date = models.DateField(default=timezone.localdate)
    start_time = models.TimeField()
    end_time = models.TimeField()
    consultation_methods = models.JSONField(
        default=list,
        help_text="Supported consultation methods for this period, e.g. ['IN_PERSON', 'VIRTUAL_VOICE']"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date', 'start_time']
        verbose_name_plural = "Availabilities"
        indexes = [
            models.Index(fields=['midwife', 'date', 'is_active']),
        ]

    def clean(self):
        super().clean()
        today = timezone.localdate()
        now_time = timezone.localtime().time()
        if self.date and self.date < today:
            raise ValidationError({'date': _('Availability date cannot be in the past.')})
        if self.date == today and self.start_time and self.start_time <= now_time:
            raise ValidationError({'start_time': _('Start time must be strictly later than current time for today\'s availability.')})
        if self.start_time and self.end_time and self.start_time >= self.end_time:
            raise ValidationError({'start_time': _('Start time must be earlier than end time.')})

    def __str__(self):
        return f"{self.midwife.user.username} on {self.date} ({self.start_time}-{self.end_time})"


class TimeSlot(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    availability = models.ForeignKey(
        Availability,
        on_delete=models.CASCADE,
        related_name='time_slots',
        null=True,
        blank=True
    )
    midwife = models.ForeignKey(MidwifeProfile, on_delete=models.CASCADE, related_name='time_slots')
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_available = models.BooleanField(default=True)

    class Meta:
        indexes = [
            models.Index(fields=['midwife', 'date', 'is_available']),
        ]

    def __str__(self):
        return f"Slot for {self.midwife.user.username} on {self.date} ({self.start_time}-{self.end_time})"


class Appointment(models.Model):
    class AppointmentType(models.TextChoices):
        IN_PERSON = 'IN_PERSON', _('In-Person Consultation')
        VIRTUAL_VOICE = 'VIRTUAL_VOICE', _('Virtual Voice Consultation')
        VIRTUAL_VIDEO = 'VIRTUAL_VIDEO', _('Virtual Video Consultation')

    class AppointmentStatus(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        CONFIRMED = 'CONFIRMED', _('Confirmed')
        COMPLETED = 'COMPLETED', _('Completed')
        CANCELLED = 'CANCELLED', _('Cancelled')
        REJECTED = 'REJECTED', _('Rejected')
        MISSED = 'MISSED', _('Missed')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment_number = models.CharField(max_length=50, unique=True, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='appointments')
    midwife = models.ForeignKey(MidwifeProfile, on_delete=models.CASCADE, related_name='appointments')
    appointment_type = models.CharField(max_length=20, choices=AppointmentType.choices)
    scheduled_date = models.DateField(db_index=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.PENDING,
        db_index=True
    )
    reason = models.TextField(blank=True)
    fee = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='created_appointments'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-scheduled_date', '-start_time']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['midwife', 'status']),
            models.Index(fields=['scheduled_date', 'start_time']),
        ]

    def save(self, *args, **kwargs):
        if not self.appointment_number:
            self.appointment_number = f"APT-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Appointment {self.appointment_number} - {self.user.username} with {self.midwife.user.username}"
