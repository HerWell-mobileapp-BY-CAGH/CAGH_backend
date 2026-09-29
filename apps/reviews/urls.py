from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ReviewViewSet, AdminPublicReviewListView, AdminMidwifeReviewListView, AdminReviewSummaryView

router = DefaultRouter()
router.register(r'feedback', ReviewViewSet, basename='review')

urlpatterns = [
    path('admin/public/', AdminPublicReviewListView.as_view(), name='admin-public-review-list'),
    path('admin/summary/', AdminReviewSummaryView.as_view(), name='admin-review-summary'),
    path('admin/midwives/<uuid:midwife_id>/', AdminMidwifeReviewListView.as_view(), name='admin-midwife-review-list'),
    path('', include(router.urls)),
]
