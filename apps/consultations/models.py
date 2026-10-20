import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from apps.appointments.models import Appointment
from apps.midwives.models import MidwifeProfile


class Consultation(models.Model):
    class ConsultationStatus(models.TextChoices):
        SCHEDULED = 'SCHEDULED', _('Scheduled')
        ACTIVE = 'ACTIVE', _('Active')
        COMPLETED = 'COMPLETED', _('Completed')
        CANCELLED = 'CANCELLED', _('Cancelled')

    class ConsultationType(models.TextChoices):
        IN_PERSON = 'IN_PERSON', _('In-Person')
        VIRTUAL_VOICE = 'VIRTUAL_VOICE', _('Virtual Voice')
        VIRTUAL_VIDEO = 'VIRTUAL_VIDEO', _('Virtual Video')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.OneToOneField(
        Appointment,
        on_delete=models.CASCADE,
        related_name='consultation'
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='consultations')
    midwife = models.ForeignKey(MidwifeProfile, on_delete=models.CASCADE, related_name='consultations')
    consultation_type = models.CharField(max_length=20, choices=ConsultationType.choices)
    status = models.CharField(
        max_length=20,
        choices=ConsultationStatus.choices,
        default=ConsultationStatus.SCHEDULED,
        db_index=True
    )
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    summary = models.TextField(blank=True)
    diagnosis = models.TextField(blank=True)
    recommendation = models.TextField(blank=True)
    follow_up_required = models.BooleanField(default=False)
    follow_up_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['midwife', 'status']),
        ]

    def __str__(self):
        return f"Consultation {self.id} - {self.user.username} & Midwife {self.midwife.user.username}"


    @property
    def voice_session(self):
        active = self.voice_sessions.exclude(
            status__in=[
                VoiceSession.VoiceSessionStatus.CANCELLED,
                VoiceSession.VoiceSessionStatus.DECLINED,
                VoiceSession.VoiceSessionStatus.MISSED,
                VoiceSession.VoiceSessionStatus.ENDED,
                VoiceSession.VoiceSessionStatus.FAILED,
            ]
        ).order_by('-created_at').first()
        if active:
            return active
        return self.voice_sessions.order_by('-created_at').first()

class ConsultationNote(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    consultation = models.ForeignKey(Consultation, on_delete=models.CASCADE, related_name='notes')
    midwife = models.ForeignKey(MidwifeProfile, on_delete=models.CASCADE, related_name='consultation_notes')
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Note by {self.midwife.user.username} on Consultation {self.consultation.id}"


class VoiceSession(models.Model):
    class VoiceSessionStatus(models.TextChoices):
        INITIATED = 'INITIATED', _('Initiated')
        RINGING = 'RINGING', _('Ringing')
        ACCEPTED = 'ACCEPTED', _('Accepted')
        ONGOING = 'ONGOING', _('Ongoing')
        DECLINED = 'DECLINED', _('Declined')
        MISSED = 'MISSED', _('Missed')
        CANCELLED = 'CANCELLED', _('Cancelled')
        ENDED = 'ENDED', _('Ended')
        FAILED = 'FAILED', _('Failed')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    consultation = models.ForeignKey(Consultation, on_delete=models.CASCADE, related_name='voice_sessions')
    caller = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='initiated_voice_sessions',
        null=True,
        blank=True
    )
    session_key = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=VoiceSessionStatus.choices, default=VoiceSessionStatus.INITIATED, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        indexes = [
            models.Index(fields=['consultation', 'status']),
        ]

    def __str__(self):
        return f"Voice Session {self.session_key} - {self.status}"



class VideoSession(models.Model):
    class VideoSessionStatus(models.TextChoices):
        INITIATED = 'INITIATED', _('Initiated')
        ONGOING = 'ONGOING', _('Ongoing')
        ENDED = 'ENDED', _('Ended')
        FAILED = 'FAILED', _('Failed')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    consultation = models.OneToOneField(Consultation, on_delete=models.CASCADE, related_name='video_session')
    session_key = models.CharField(max_length=255, unique=True)
    status = models.CharField(max_length=20, choices=VideoSessionStatus.choices, default=VideoSessionStatus.INITIATED)
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Video Session {self.session_key} - {self.status}"

