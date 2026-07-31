from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import HospitalViewSet, MidwifeProfileViewSet, SavedMidwifeViewSet

router = DefaultRouter()
router.register(r'hospitals', HospitalViewSet, basename='hospital')
router.register(r'profiles', MidwifeProfileViewSet, basename='midwife-profile')
router.register(r'saved', SavedMidwifeViewSet, basename='saved-midwife')

urlpatterns = [
    path('', include(router.urls)),
]
