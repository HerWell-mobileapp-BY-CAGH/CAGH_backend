from django.db import models
from rest_framework import viewsets, permissions, status, generics
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from django.shortcuts import get_object_or_404

from .models import Review
from .serializers import ReviewSerializer
from apps.midwives.models import MidwifeProfile
from apps.users.permissions import IsAdmin


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


class AdminPublicReviewListView(generics.ListAPIView):
    """Administrator view of every review visible through the public API."""

    serializer_class = ReviewSerializer
    permission_classes = [IsAdmin]
    queryset = Review.objects.select_related('user', 'midwife', 'midwife__user').all()

    @extend_schema(
        summary="List all public reviews for administrators",
        description=(
            "Returns the complete review feed, newest first, for the admin dashboard. "
            "The normal DRF page query parameter (`page`) is supported."
        ),
        responses={200: ReviewSerializer(many=True), 401: OpenApiResponse(description="Authentication required"), 403: OpenApiResponse(description="Administrator access required")},
        tags=["Reviews & Ratings"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        return self.queryset.order_by('-created_at')


class AdminMidwifeReviewListView(generics.ListAPIView):
    """Administrator view of reviews for one midwife profile."""

    serializer_class = ReviewSerializer
    permission_classes = [IsAdmin]
    # Gives schema generation a safe model source; requests use get_queryset.
    queryset = Review.objects.none()

    @extend_schema(
        summary="List reviews for one midwife for administrators",
        description="Returns reviews left for the requested midwife profile, newest first.",
        parameters=[
            OpenApiParameter(
                name="midwife_id",
                location=OpenApiParameter.PATH,
                required=True,
                description="UUID of the MidwifeProfile, not the user UUID.",
            ),
        ],
        responses={200: ReviewSerializer(many=True), 404: OpenApiResponse(description="Midwife profile not found")},
        tags=["Reviews & Ratings"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_queryset(self):
        midwife = get_object_or_404(MidwifeProfile, pk=self.kwargs['midwife_id'])
        return Review.objects.filter(midwife=midwife).select_related(
            'user', 'midwife', 'midwife__user'
        ).order_by('-created_at')


class AdminReviewSummaryView(APIView):
    """Administrator-only aggregate used by the feedback dashboard cards."""

    permission_classes = [IsAdmin]

    @extend_schema(
        summary="Get administrator review summary",
        description="Returns totals, average rating, and a complete 1–5 rating distribution.",
        tags=["Reviews & Ratings"],
    )
    def get(self, request):
        aggregates = Review.objects.aggregate(
            average_rating=models.Avg('rating'),
            total_reviews=models.Count('id'),
        )
        total_reviews = aggregates['total_reviews']
        counts = {
            rating: Review.objects.filter(rating=rating).count()
            for rating in range(1, 6)
        }
        return Response({
            'total_reviews': total_reviews,
            'average_rating': round(aggregates['average_rating'] or 0, 2),
            'max_rating': 5,
            'distribution': [
                {
                    'rating': rating,
                    'count': counts[rating],
                    'percentage': round((counts[rating] / total_reviews) * 100, 2)
                    if total_reviews else 0,
                }
                for rating in range(5, 0, -1)
            ],
        })

