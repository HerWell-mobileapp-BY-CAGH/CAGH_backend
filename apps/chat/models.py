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
    status = models.CharField(max_length=20, choices=RoomStatus.choices, default=RoomStatus.REQUESTED)
    created_at = models.DateTimeField(auto_now_add=True)

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
    status = models.CharField(max_length=20, choices=MessageStatus.choices, default=MessageStatus.SENT)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Message by {self.sender.username} in Room {self.chat_room.id}"


class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message = models.OneToOneField(Message, on_delete=models.CASCADE, related_name='attachment')
    file_url = models.URLField(max_length=500)
    file_type = models.CharField(max_length=50)
    size = models.PositiveIntegerField(help_text="File size in bytes")

    def __str__(self):
        return f"Attachment for Message {self.message.id}"
