from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AvailabilityViewSet, TimeSlotViewSet, AppointmentViewSet

router = DefaultRouter()
router.register(r'availability', AvailabilityViewSet, basename='availability')
router.register(r'time-slots', TimeSlotViewSet, basename='time-slot')
router.register(r'slots', TimeSlotViewSet, basename='slot-alias')
router.register(r'bookings', AppointmentViewSet, basename='appointment')
router.register(r'', AppointmentViewSet, basename='appointment-root')


urlpatterns = [
    path('', include(router.urls)),
]
