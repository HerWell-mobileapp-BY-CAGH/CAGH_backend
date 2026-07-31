import uuid
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from apps.midwives.models import MidwifeProfile
from apps.consultations.models import Consultation


class Review(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='reviews')
    midwife = models.ForeignKey(MidwifeProfile, on_delete=models.CASCADE, related_name='reviews')
    consultation = models.OneToOneField(
        Consultation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='review'
    )
    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField(blank=True)
    is_anonymous = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        reviewer = "Anonymous" if self.is_anonymous else self.user.username
        return f"Review ({self.rating}/5) by {reviewer} for Midwife {self.midwife.user.username}"
