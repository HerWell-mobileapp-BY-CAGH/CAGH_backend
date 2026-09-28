import uuid
from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _


class AIQuestion(models.Model):
    class FeedbackStatus(models.TextChoices):
        THUMBS_UP = 'THUMBS_UP', _('Thumbs Up')
        THUMBS_DOWN = 'THUMBS_DOWN', _('Thumbs Down')
        LIKE = 'LIKE', _('Like')
        DISLIKE = 'DISLIKE', _('Dislike')
        NONE = 'NONE', _('None')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_questions')
    question = models.TextField()
    response = models.TextField()
    feedback = models.CharField(max_length=15, choices=FeedbackStatus.choices, default=FeedbackStatus.NONE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]

    def __str__(self):
        return f"AI Q&A for {self.user.username} at {self.created_at}"


class AIConversation(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='ai_conversations')
    title = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at', '-created_at']
        indexes = [
            models.Index(fields=['user', '-updated_at']),
        ]

    def __str__(self):
        return f"Conversation '{self.title or 'Untitled'}' ({self.user.username})"


class AIMessage(models.Model):
    class MessageRole(models.TextChoices):
        USER = 'user', _('User')
        ASSISTANT = 'assistant', _('Assistant')
        SYSTEM = 'system', _('System')

    class SafetyLevel(models.TextChoices):
        NORMAL = 'normal', _('Normal')
        URGENT = 'urgent', _('Urgent')
        EMERGENCY = 'emergency', _('Emergency')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    conversation = models.ForeignKey(AIConversation, on_delete=models.CASCADE, related_name='messages')
    role = models.CharField(max_length=20, choices=MessageRole.choices, default=MessageRole.USER)
    content = models.TextField()
    category = models.CharField(max_length=100, blank=True, default='GENERAL_HEALTH')
    safety_level = models.CharField(max_length=20, choices=SafetyLevel.choices, default=SafetyLevel.NORMAL)
    is_emergency = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['conversation', 'created_at']),
        ]

    def __str__(self):
        return f"[{self.role}] ({self.safety_level}) {self.content[:30]}..."

