from rest_framework import serializers
from .models import ChatRoom, Message, Attachment
from apps.users.user_serializers import UserSerializer
from apps.midwives.serializers import MidwifeProfileSerializer


class AttachmentSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = ('id', 'message', 'file', 'file_url', 'file_type', 'size')
        read_only_fields = ('id', 'message')

    def get_file_url(self, obj):
        if obj.file:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.file.url)
            return obj.file.url
        return None


class MessageSerializer(serializers.ModelSerializer):
    attachment = AttachmentSerializer(read_only=True)
    sender_detail = UserSerializer(source='sender', read_only=True)

    class Meta:
        model = Message
        fields = '__all__'
        read_only_fields = ('id', 'chat_room', 'sender', 'sent_at', 'read_at')



class ChatRoomSerializer(serializers.ModelSerializer):
    user_detail = UserSerializer(source='user', read_only=True)
    midwife_detail = MidwifeProfileSerializer(source='midwife', read_only=True)
    latest_message = serializers.SerializerMethodField(read_only=True)
    unread_count = serializers.SerializerMethodField(read_only=True)
    initial_message = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = ChatRoom
        fields = '__all__'
        read_only_fields = ('id', 'user', 'status', 'created_at', 'updated_at')

    def get_latest_message(self, obj):
        if hasattr(obj, 'prefetched_messages'):
            messages = obj.prefetched_messages
            return MessageSerializer(messages[0], context=self.context).data if messages else None
        latest = obj.messages.select_related('sender', 'sender__profile', 'attachment').order_by('-sent_at').first()
        return MessageSerializer(latest, context=self.context).data if latest else None

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return 0

        if hasattr(obj, 'prefetched_messages'):
            return sum(
                1 for m in obj.prefetched_messages
                if m.sender_id != request.user.id and m.status in [Message.MessageStatus.SENT, Message.MessageStatus.DELIVERED]
            )

        return obj.messages.exclude(sender=request.user).filter(status__in=[Message.MessageStatus.SENT, Message.MessageStatus.DELIVERED]).count()

