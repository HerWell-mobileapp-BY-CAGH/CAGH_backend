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
    path('dashboard/', MidwifeDashboardView.as_view(), name='midwife-dashboard'),
    path('', include(router.urls)),
]

