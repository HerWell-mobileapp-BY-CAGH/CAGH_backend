from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db import models
from .models import ChatRoom, Message, Attachment
from .serializers import ChatRoomSerializer, MessageSerializer, AttachmentSerializer


class ChatRoomViewSet(viewsets.ModelViewSet):
    queryset = ChatRoom.objects.all()
    serializer_class = ChatRoomSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'midwife_profile'):
            return ChatRoom.objects.filter(
                models.Q(user=user) | models.Q(midwife=user.midwife_profile)
            )
        return ChatRoom.objects.filter(user=user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, status=ChatRoom.RoomStatus.REQUESTED)

    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        room = self.get_object()
        if not hasattr(request.user, 'midwife_profile') or request.user.midwife_profile != room.midwife:
            return Response({'error': 'Only the assigned midwife can accept chat requests.'}, status=status.HTTP_403_FORBIDDEN)
        room.status = ChatRoom.RoomStatus.ACCEPTED
        room.save()
        return Response({'status': 'Chat request accepted'})

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        room = self.get_object()
        if not hasattr(request.user, 'midwife_profile') or request.user.midwife_profile != room.midwife:
            return Response({'error': 'Only the assigned midwife can reject chat requests.'}, status=status.HTTP_403_FORBIDDEN)
        room.status = ChatRoom.RoomStatus.REJECTED
        room.save()
        return Response({'status': 'Chat request rejected'})

    @action(detail=True, methods=['get', 'post'])
    def messages(self, request, pk=None):
        room = self.get_object()
        if request.method == 'GET':
            messages = room.messages.order_by('sent_at')
            serializer = MessageSerializer(messages, many=True)
            return Response(serializer.data)

        elif request.method == 'POST':
            if room.status != ChatRoom.RoomStatus.ACCEPTED:
                return Response(
                    {'error': 'Cannot send messages until the chat request has been accepted.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            serializer = MessageSerializer(data=request.data)
            if serializer.is_valid():
                msg = serializer.save(chat_room=room, sender=request.user)
                
                # Check for attachment
                file_url = request.data.get('file_url')
                file_type = request.data.get('file_type')
                file_size = request.data.get('file_size')
                if file_url and file_type:
                    Attachment.objects.create(
                        message=msg,
                        file_url=file_url,
                        file_type=file_type,
                        size=file_size or 0
                    )
                return Response(MessageSerializer(msg).data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
