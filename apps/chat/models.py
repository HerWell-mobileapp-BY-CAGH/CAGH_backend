import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from apps.midwives.models import MidwifeProfile


class ChatRoom(models.Model):
    class RoomStatus(models.TextChoices):
        REQUESTED = 'REQUESTED', _('Requested')
        ACCEPTED = 'ACCEPTED', _('Accepted')
        REJECTED = 'REJECTED', _('Rejected')
        CLOSED = 'CLOSED', _('Closed')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='chat_rooms')
    midwife = models.ForeignKey(MidwifeProfile, on_delete=models.CASCADE, related_name='chat_rooms')
    status = models.CharField(max_length=20, choices=RoomStatus.choices, default=RoomStatus.REQUESTED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['user', 'status']),
            models.Index(fields=['midwife', 'status']),
        ]

    def __str__(self):
        return f"Chat Room ({self.user.username} & Midwife {self.midwife.user.username}) - {self.status}"


class Message(models.Model):
    class MessageType(models.TextChoices):
        TEXT = 'TEXT', _('Text')
        IMAGE = 'IMAGE', _('Image')
        PDF = 'PDF', _('PDF')
        VOICE_NOTE = 'VOICE_NOTE', _('Voice Note')

    class MessageStatus(models.TextChoices):
        SENT = 'SENT', _('Sent')
        DELIVERED = 'DELIVERED', _('Delivered')
        READ = 'READ', _('Read')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    chat_room = models.ForeignKey(ChatRoom, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='sent_messages')
    message_type = models.CharField(max_length=20, choices=MessageType.choices, default=MessageType.TEXT)
    content = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=MessageStatus.choices, default=MessageStatus.SENT, db_index=True)
    sent_at = models.DateTimeField(auto_now_add=True, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['sent_at']
        indexes = [
            models.Index(fields=['chat_room', 'sent_at']),
            models.Index(fields=['chat_room', 'status']),
        ]

    def __str__(self):
        return f"Message by {self.sender.username} in Room {self.chat_room.id}"


class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.OneToOneField(Message, on_delete=models.CASCADE, related_name='attachment')
    file = models.FileField(upload_to='chat/attachments/', blank=True, null=True)
    file_type = models.CharField(max_length=50)
    size = models.PositiveIntegerField(default=0, help_text="File size in bytes")

    def __str__(self):
        return f"Attachment for Message {self.message.id}"

