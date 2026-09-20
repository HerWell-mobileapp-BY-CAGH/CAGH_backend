import uuid
from django.db import models
from django.conf import settings


class Notification(models.Model):
    class NotificationType(models.TextChoices):
        APPOINTMENT = 'APPOINTMENT', 'Appointment'
        CHAT = 'CHAT', 'Chat'
        CONSULTATION = 'CONSULTATION', 'Consultation'
        PREGNANCY_MILESTONE = 'PREGNANCY_MILESTONE', 'Pregnancy Milestone'
        MENSTRUAL_REMINDER = 'MENSTRUAL_REMINDER', 'Menstrual Reminder'
        SYSTEM = 'SYSTEM', 'System Announcement'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    body = models.TextField()
    type = models.CharField(max_length=50)
    action = models.CharField(max_length=100, blank=True)
    reference_id = models.CharField(max_length=100, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read', '-created_at']),
        ]

    def __str__(self):
        return f"Notification '{self.title}' for {self.user.username}"


class DeviceToken(models.Model):
    class Platform(models.TextChoices):
        ANDROID = 'ANDROID', 'Android'
        IOS = 'IOS', 'iOS'
        WEB = 'WEB', 'Web'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='device_tokens')
    token = models.CharField(max_length=500, unique=True)
    platform = models.CharField(max_length=20, choices=Platform.choices, default=Platform.ANDROID)
    is_active = models.BooleanField(default=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        return f"Token ({self.platform}) for {self.user.username}"


class NotificationPreference(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notification_preferences')
    enable_push_notifications = models.BooleanField(default=True)
    appointment_reminders = models.BooleanField(default=True)
    chat_messages = models.BooleanField(default=True)
    booking_updates = models.BooleanField(default=True)
    consultation_updates = models.BooleanField(default=True)
    pregnancy_menstrual_reminders = models.BooleanField(default=True)
    system_announcements = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Notification Preferences for {self.user.username}"

