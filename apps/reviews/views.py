from rest_framework import viewsets, permissions
from .models import Review
from .serializers import ReviewSerializer


class ReviewViewSet(viewsets.ModelViewSet):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = Review.objects.all()
        midwife_id = self.request.query_params.get('midwife_id')
        if midwife_id:
            queryset = queryset.filter(midwife_id=midwife_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
