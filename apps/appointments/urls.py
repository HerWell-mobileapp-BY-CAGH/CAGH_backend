from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AvailabilityViewSet, TimeSlotViewSet, AppointmentViewSet

router = DefaultRouter()
router.register(r'availability', AvailabilityViewSet, basename='availability')
router.register(r'time-slots', TimeSlotViewSet, basename='time-slot')
router.register(r'bookings', AppointmentViewSet, basename='appointment')

urlpatterns = [
    path('', include(router.urls)),
]
