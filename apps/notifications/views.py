from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema

from .models import Notification, DeviceToken, NotificationPreference
from .serializers import (
    NotificationSerializer,
    DeviceTokenSerializer,
    NotificationPreferenceSerializer,
)


class NotificationViewSet(viewsets.ModelViewSet):
    """
    3.12 Notification Module
    FR-029 Push Notifications (FCM / APNs token registration & delivery)
    FR-030 Notification Preferences management
    """

    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user).order_by('-created_at')

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)
        unread_count = Notification.objects.filter(user=request.user, is_read=False).count()

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            res = self.get_paginated_response(serializer.data)
            res.data['unread_count'] = unread_count
            return res

        serializer = self.get_serializer(queryset, many=True)
        return Response({
            'unread_count': unread_count,
            'results': serializer.data,
        }, status=status.HTTP_200_OK)

    @extend_schema(summary="Mark a notification as read", tags=["Notifications"])
    @action(detail=True, methods=['post'])
    def mark_as_read(self, request, pk=None):
        notification = self.get_object()
        notification.is_read = True
        notification.save()
        return Response({'status': 'READ', 'message': 'Notification marked as read.'}, status=status.HTTP_200_OK)

    @extend_schema(summary="Mark all notifications as read", tags=["Notifications"])
    @action(detail=False, methods=['post'])
    def mark_all_as_read(self, request):
        count = Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'status': 'READ', 'marked_read_count': count}, status=status.HTTP_200_OK)

    @extend_schema(summary="Get count of unread notifications", tags=["Notifications"])
    @action(detail=False, methods=['get'])
    def unread_count(self, request):
        count = Notification.objects.filter(user=request.user, is_read=False).count()
        return Response({'unread_count': count}, status=status.HTTP_200_OK)

    @extend_schema(summary="FR-030: Get or update user notification preferences", tags=["Notifications"])
    @action(detail=False, methods=['get', 'put', 'patch'])
    def preferences(self, request):
        pref, _ = NotificationPreference.objects.get_or_create(user=request.user)

        if request.method == 'GET':
            serializer = NotificationPreferenceSerializer(pref)
            return Response(serializer.data, status=status.HTTP_200_OK)

        serializer = NotificationPreferenceSerializer(pref, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(summary="FR-029: Register mobile device FCM push token", tags=["Notifications"])
    @action(detail=False, methods=['post'], url_path='register-device')
    def register_device(self, request):
        token_str = request.data.get('token')
        platform_str = request.data.get('platform', 'ANDROID').upper()

        if not token_str:
            return Response({'error': 'Device push token string is required.'}, status=status.HTTP_400_BAD_REQUEST)

        device_token, created = DeviceToken.objects.update_or_create(
            token=token_str,
            defaults={
                'user': request.user,
                'platform': platform_str if platform_str in DeviceToken.Platform.values else DeviceToken.Platform.ANDROID,
                'is_active': True,
            }
        )

        serializer = DeviceTokenSerializer(device_token)
        return Response({
            'status': 'REGISTERED',
            'created': created,
            'device_token': serializer.data,
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

