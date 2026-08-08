from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import ChatRoomViewSet

router = DefaultRouter()
router.register(r'rooms', ChatRoomViewSet, basename='chat-room')
router.register(r'', ChatRoomViewSet, basename='chat-root')


urlpatterns = [
    path('', include(router.urls)),
]
