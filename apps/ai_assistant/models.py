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

    def __str__(self):
        return f"AI Q&A for {self.user.username} at {self.created_at}"

