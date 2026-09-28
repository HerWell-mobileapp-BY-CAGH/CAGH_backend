from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import models
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema

from .models import ChatRoom, Message, Attachment
from .serializers import ChatRoomSerializer, MessageSerializer, AttachmentSerializer
from apps.notifications.models import Notification
from apps.notifications.call_notifications import send_general_push_notification


class ChatRoomViewSet(viewsets.ModelViewSet):
    """
    Handles chat requests, midwife accept/reject workflow, real-time messaging,
    attachments, and read receipts.
    """

    queryset = ChatRoom.objects.all().select_related(
        'user', 'user__profile', 'midwife', 'midwife__user', 'midwife__user__profile', 'midwife__hospital'
    )
    serializer_class = ChatRoomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = ChatRoom.objects.all().select_related(
            'user', 'user__profile', 'user__preferences', 'user__midwife_profile', 'user__midwife_profile__hospital',
            'midwife', 'midwife__user', 'midwife__user__profile', 'midwife__user__preferences', 'midwife__user__midwife_profile', 'midwife__hospital'
        )

        if self.action in ['retrieve', 'accept', 'reject', 'messages', 'read']:
            return queryset

        messages_qs = Message.objects.select_related(
            'sender', 'sender__profile', 'sender__preferences', 'sender__midwife_profile', 'sender__midwife_profile__hospital', 'attachment'
        ).order_by('-sent_at')
        queryset = queryset.prefetch_related(
            models.Prefetch('messages', queryset=messages_qs, to_attr='prefetched_messages'),
            'midwife__qualifications', 'midwife__certificates', 'midwife__expertises'
        )

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
            title_mw = "New Chat Request"
            body_mw = f"User {self.request.user.username} sent you a direct message chat request."
            Notification.objects.create(
                user=room.midwife.user,
                title=title_mw,
                body=body_mw,
                type="CHAT",
                action="CHAT_REQUEST",
                reference_id=str(room.id),
            )
            send_general_push_notification(
                user=room.midwife.user,
                title=title_mw,
                body=body_mw,
                extra_data={"type": "CHAT", "action": "CHAT_REQUEST", "room_id": str(room.id)},
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
        title_u = "Chat Request Accepted"
        body_u = f"Midwife {request.user.username} accepted your chat request. You can now chat freely."
        Notification.objects.create(
            user=room.user,
            title=title_u,
            body=body_u,
            type="CHAT",
            action="CHAT_ACCEPTED",
            reference_id=str(room.id),
        )
        send_general_push_notification(
            user=room.user,
            title=title_u,
            body=body_u,
            extra_data={"type": "CHAT", "action": "CHAT_ACCEPTED", "room_id": str(room.id)},
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
        title_u = "Chat Request Declined"
        body_u = f"Midwife {request.user.username} is unavailable for direct chat right now. You may book an appointment for consultations."
        Notification.objects.create(
            user=room.user,
            title=title_u,
            body=body_u,
            type="CHAT",
            action="CHAT_REJECTED",
            reference_id=str(room.id),
        )
        send_general_push_notification(
            user=room.user,
            title=title_u,
            body=body_u,
            extra_data={"type": "CHAT", "action": "CHAT_REJECTED", "room_id": str(room.id)},
        )

        return Response({'status': 'REJECTED', 'message': 'Chat request rejected.'}, status=status.HTTP_200_OK)

    @extend_schema(summary="Get or send room messages", tags=["Chat"])
    @action(detail=True, methods=['get', 'post'])
    def messages(self, request, pk=None):
        room = self.get_object()
        if request.method == 'GET':
            messages = room.messages.select_related(
                'sender', 'sender__profile', 'sender__preferences', 'sender__midwife_profile', 'sender__midwife_profile__hospital', 'attachment'
            ).order_by('sent_at')
            serializer = MessageSerializer(messages, many=True, context={'request': request})
            return Response(serializer.data, status=status.HTTP_200_OK)

        elif request.method == 'POST':
            if room.status != ChatRoom.RoomStatus.ACCEPTED:
                return Response(
                    {'error': 'Chat request pending acceptance. You cannot send further messages until the midwife accepts the request.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            serializer = MessageSerializer(data=request.data, context={'request': request})
            if serializer.is_valid():
                msg = serializer.save(chat_room=room, sender=request.user)

                # Process media attachment (Image, PDF, Voice Note) uploaded directly as file
                file_obj = request.FILES.get('file') or request.data.get('file')
                file_type = request.data.get('file_type', 'application/octet-stream')
                file_size = request.data.get('file_size', getattr(file_obj, 'size', 0) if file_obj else 0)

                if file_obj:
                    Attachment.objects.create(
                        message=msg,
                        file=file_obj,
                        file_type=file_type,
                        size=file_size,
                    )

                room.save(update_fields=['updated_at'])

                serialized_msg = MessageSerializer(msg, context={'request': request}).data

                # Real-time WebSocket broadcast to active room subscribers
                channel_layer = get_channel_layer()
                if channel_layer:
                    try:
                        async_to_sync(channel_layer.group_send)(
                            f'chat_{room.id}',
                            {
                                'type': 'chat_message',
                                'message': serialized_msg,
                            }
                        )
                    except Exception:
                        pass

                # Notify recipient
                recipient = room.midwife.user if request.user == room.user else room.user
                Notification.objects.create(
                    user=recipient,
                    title=f"New message from {request.user.username}",
                    body=msg.content[:100] if msg.content else "Sent an attachment",
                    type="CHAT",
                    action="CHAT_MESSAGE",
                    reference_id=str(room.id),
                )

                return Response(serialized_msg, status=status.HTTP_201_CREATED)

            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(summary="Mark unread room messages as READ", tags=["Chat"])
    @action(detail=True, methods=['post'])
    def read(self, request, pk=None):
        room = self.get_object()
        now = timezone.now()

        unread = room.messages.exclude(sender=request.user).filter(
            status__in=[Message.MessageStatus.SENT, Message.MessageStatus.DELIVERED]
        )
        read_ids = [str(m.id) for m in unread]
        count = unread.update(status=Message.MessageStatus.READ, read_at=now)

        if count > 0:
            channel_layer = get_channel_layer()
            if channel_layer:
                try:
                    async_to_sync(channel_layer.group_send)(
                        f'chat_{room.id}',
                        {
                            'type': 'messages_read',
                            'reader_id': str(request.user.id),
                            'read_at': now.isoformat(),
                            'message_ids': read_ids,
                        }
                    )
                except Exception:
                    pass

        return Response({
            'status': 'READ',
            'marked_read_count': count,
            'read_at': now,
        }, status=status.HTTP_200_OK)


