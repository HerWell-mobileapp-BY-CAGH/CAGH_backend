from rest_framework import serializers
from .models import ChatRoom, Message, Attachment
from apps.users.user_serializers import UserSerializer
from apps.midwives.serializers import MidwifeProfileSerializer


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = '__all__'
        read_only_fields = ('id', 'message')


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
        latest = obj.messages.order_by('-sent_at').first()
        if latest:
            return MessageSerializer(latest).data
        return None

    def get_unread_count(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.messages.exclude(sender=request.user).filter(status__in=[Message.MessageStatus.SENT, Message.MessageStatus.DELIVERED]).count()
        return 0

