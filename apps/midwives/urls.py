from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    HospitalViewSet,
    MidwifeProfileViewSet,
    QualificationViewSet,
    CertificateViewSet,
    ExpertiseViewSet,
    BlockedDateViewSet,
    SavedMidwifeViewSet,
    MidwifeDashboardView,
    MidwifeApplicationListView,
    MidwifeApplicationDetailView,
    MidwifeApplicationReviewView,
)

router = DefaultRouter()
router.register(r'hospitals', HospitalViewSet, basename='hospital')
router.register(r'profiles', MidwifeProfileViewSet, basename='midwife-profile')
router.register(r'qualifications', QualificationViewSet, basename='midwife-qualification')
router.register(r'certificates', CertificateViewSet, basename='midwife-certificate')
router.register(r'expertises', ExpertiseViewSet, basename='midwife-expertise')
router.register(r'blocked-dates', BlockedDateViewSet, basename='midwife-blocked-date')
router.register(r'saved', SavedMidwifeViewSet, basename='saved-midwife')

urlpatterns = [
    path('applications/', MidwifeApplicationListView.as_view(), name='midwife-applications-list'),
    path('applications/<uuid:pk>/', MidwifeApplicationDetailView.as_view(), name='midwife-application-detail'),
    path('applications/<uuid:pk>/review/', MidwifeApplicationReviewView.as_view(), name='midwife-application-review'),
    path('dashboard/', MidwifeDashboardView.as_view(), name='midwife-dashboard'),
    path('', include(router.urls)),
]

