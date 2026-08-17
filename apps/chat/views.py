from django.db import models
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema

from .models import ChatRoom, Message, Attachment
from .serializers import ChatRoomSerializer, MessageSerializer, AttachmentSerializer
from apps.notifications.models import Notification


class ChatRoomViewSet(viewsets.ModelViewSet):
    """
    Module 6 — Chat System
    Handles chat requests, midwife accept/reject workflow, real-time messaging,
    attachments (Image, PDF, Voice Note), and read receipts.
    """

    queryset = ChatRoom.objects.all().select_related('user', 'midwife', 'midwife__user')
    serializer_class = ChatRoomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = ChatRoom.objects.all().select_related('user', 'midwife', 'midwife__user')

        if self.action in ['retrieve', 'accept', 'reject', 'messages', 'read']:
            return queryset

        if hasattr(user, 'midwife_profile'):
            queryset = queryset.filter(models.Q(user=user) | models.Q(midwife=user.midwife_profile))
        elif not (user.is_staff or getattr(user, 'role', '') == 'ADMIN'):
            queryset = queryset.filter(user=user)

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                models.Q(midwife__user__first_name__icontains=search) |
                models.Q(midwife__user__last_name__icontains=search) |
                models.Q(midwife__user__username__icontains=search) |
                models.Q(user__first_name__icontains=search) |
                models.Q(user__last_name__icontains=search) |
                models.Q(user__username__icontains=search) |
                models.Q(messages__content__icontains=search)
            ).distinct()

        return queryset

    def perform_create(self, serializer):
        initial_text = serializer.validated_data.pop('initial_message', None)
        room = serializer.save(user=self.request.user, status=ChatRoom.RoomStatus.REQUESTED)

        # Create initial text message if provided by user
        if initial_text:
            Message.objects.create(
                chat_room=room,
                sender=self.request.user,
                content=initial_text,
                message_type=Message.MessageType.TEXT,
                status=Message.MessageStatus.SENT,
            )

        # Notify midwife of new chat request
        if room.midwife and room.midwife.user:
            Notification.objects.create(
                user=room.midwife.user,
                title="New Chat Request",
                body=f"User {self.request.user.username} sent you a direct message chat request.",
                type="CHAT",
                action="CHAT_REQUEST",
                reference_id=str(room.id),
            )

    @extend_schema(summary="Midwife action: Accept chat request", tags=["Chat"])
    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        room = self.get_object()
        if not hasattr(request.user, 'midwife_profile') or request.user.midwife_profile != room.midwife:
            return Response({'error': 'Only the assigned midwife can accept chat requests.'}, status=status.HTTP_403_FORBIDDEN)

        room.status = ChatRoom.RoomStatus.ACCEPTED
        room.save()

        # Notify user
        Notification.objects.create(
            user=room.user,
            title="Chat Request Accepted",
            body=f"Midwife {request.user.username} accepted your chat request. You can now chat freely.",
            type="CHAT",
            action="CHAT_ACCEPTED",
            reference_id=str(room.id),
        )

        return Response({'status': 'ACCEPTED', 'message': 'Chat request accepted successfully.'}, status=status.HTTP_200_OK)

    @extend_schema(summary="Midwife action: Reject chat request", tags=["Chat"])
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        room = self.get_object()
        if not hasattr(request.user, 'midwife_profile') or request.user.midwife_profile != room.midwife:
            return Response({'error': 'Only the assigned midwife can reject chat requests.'}, status=status.HTTP_403_FORBIDDEN)

        room.status = ChatRoom.RoomStatus.REJECTED
        room.save()

        # Notify user
        Notification.objects.create(
            user=room.user,
            title="Chat Request Declined",
            body=f"Midwife {request.user.username} is unavailable for direct chat right now. You may book an appointment for consultations.",
            type="CHAT",
            action="CHAT_REJECTED",
            reference_id=str(room.id),
        )

        return Response({'status': 'REJECTED', 'message': 'Chat request rejected.'}, status=status.HTTP_200_OK)

    @extend_schema(summary="Get or send room messages", tags=["Chat"])
    @action(detail=True, methods=['get', 'post'])
    def messages(self, request, pk=None):
        room = self.get_object()
        if request.method == 'GET':
            messages = room.messages.select_related('sender', 'attachment').order_by('sent_at')
            serializer = MessageSerializer(messages, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)

        elif request.method == 'POST':
            if room.status != ChatRoom.RoomStatus.ACCEPTED:
                return Response(
                    {'error': 'Cannot send messages until the chat request has been accepted by the midwife.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            serializer = MessageSerializer(data=request.data)
            if serializer.is_valid():
                msg = serializer.save(chat_room=room, sender=request.user)

                # Process media attachment (Image, PDF, Voice Note)
                file_obj = request.FILES.get('file') or request.data.get('file') or request.data.get('file_url')
                file_type = request.data.get('file_type', 'application/octet-stream')
                file_size = request.data.get('file_size', 0)

                if file_obj:
                    Attachment.objects.create(
                        message=msg,
                        file=file_obj,
                        file_type=file_type,
                        size=file_size,
                    )

                room.save(update_fields=['updated_at'])
                return Response(MessageSerializer(msg).data, status=status.HTTP_201_CREATED)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(summary="Mark unread room messages as READ", tags=["Chat"])
    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        room = self.get_object()
        now = timezone.now()

        unread = room.messages.exclude(sender=request.user).filter(
            status__in=[Message.MessageStatus.SENT, Message.MessageStatus.DELIVERED]
        )
        count = unread.update(status=Message.MessageStatus.READ, read_at=now)

        return Response({
            'status': 'READ',
            'marked_read_count': count,
            'read_at': now,
        }, status=status.HTTP_200_OK)

