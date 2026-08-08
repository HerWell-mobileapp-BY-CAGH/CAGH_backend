from django.db import models
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from .models import Review
from .serializers import ReviewSerializer


class ReviewViewSet(viewsets.ModelViewSet):
    """
    Reviews Module
    Allows patients to leave reviews and 1-5 star ratings for completed consultations.
    Automatically recalculates midwife rating_average and rating_count.
    """

    queryset = Review.objects.all().select_related('user', 'midwife', 'midwife__user')
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = Review.objects.all().select_related('user', 'midwife', 'midwife__user')
        midwife_id = self.request.query_params.get('midwife_id')
        if midwife_id:
            queryset = queryset.filter(midwife_id=midwife_id)
        return queryset

    def perform_create(self, serializer):
        review = serializer.save(user=self.request.user)

        # Recalculate midwife ratings
        midwife = review.midwife
        reviews = Review.objects.filter(midwife=midwife)
        avg = reviews.aggregate(models.Avg('rating'))['rating__avg'] or 0.00
        count = reviews.count()

        midwife.rating_average = round(avg, 2)
        midwife.rating_count = count
        midwife.save(update_fields=['rating_average', 'rating_count'])

