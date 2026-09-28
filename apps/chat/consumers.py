import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import ChatRoom, Message, Attachment


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_id = self.scope['url_route']['kwargs']['room_id']
        self.room_group_name = f'chat_{self.room_id}'

        user = self.scope.get('user')
        if not user or user.is_anonymous:
            await self.close(code=4001)
            return

        # Verify user is a member of the room
        is_member = await self.check_room_membership(user, self.room_id)
        if not is_member:
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'room_group_name'):
            try:
                await self.channel_layer.group_discard(
                    self.room_group_name,
                    self.channel_name
                )
            except Exception:
                pass

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except ValueError:
            return

        action_type = data.get('action', 'send_message')
        user = self.scope['user']

        if action_type == 'send_message':
            content = data.get('content', '')
            message_type = data.get('message_type', 'TEXT')
            file_url = data.get('file_url')
            file_type = data.get('file_type')
            file_size = data.get('file_size', 0)

            msg_data, err_code = await self.save_message(
                room_id=self.room_id,
                sender=user,
                content=content,
                message_type=message_type,
                file_url=file_url,
                file_type=file_type,
                file_size=file_size,
            )

            if msg_data:
                await self.channel_layer.group_send(
                    self.room_group_name,
                    {
                        'type': 'chat_message',
                        'message': msg_data
                    }
                )
            elif err_code == 'REQUEST_PENDING':
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'code': 'REQUEST_PENDING',
                    'message': 'Chat request pending acceptance. You cannot send further messages until the midwife accepts the request.'
                }))
            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'code': 'MESSAGE_FAILED',
                    'message': 'Failed to send message.'
                }))

        elif action_type == 'read_receipt':
            read_ids = await self.mark_messages_as_read(self.room_id, user)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'messages_read',
                    'reader_id': str(user.id),
                    'read_at': timezone.now().isoformat(),
                    'message_ids': read_ids,
                }
            )

        elif action_type == 'typing':
            is_typing = data.get('is_typing', True)
            await self.channel_layer.group_send(
                self.room_group_name,
                {
                    'type': 'user_typing',
                    'user_id': str(user.id),
                    'username': user.username,
                    'is_typing': is_typing,
                }
            )

    async def chat_message(self, event):
        await self.send(text_data=json.dumps({
            'type': 'chat_message',
            'data': event['message']
        }))

    async def messages_read(self, event):
        await self.send(text_data=json.dumps({
            'type': 'read_receipt',
            'reader_id': event['reader_id'],
            'read_at': event['read_at'],
            'message_ids': event['message_ids']
        }))

    async def user_typing(self, event):
        await self.send(text_data=json.dumps({
            'type': 'typing_indicator',
            'user_id': event['user_id'],
            'username': event['username'],
            'is_typing': event['is_typing']
        }))

    @database_sync_to_async
    def check_room_membership(self, user, room_id):
        try:
            room = ChatRoom.objects.only('id', 'user_id', 'midwife_id').get(id=room_id)
            if user.id == room.user_id:
                return True
            if hasattr(user, 'midwife_profile') and user.midwife_profile.id == room.midwife_id:
                return True
        except ChatRoom.DoesNotExist:
            pass
        return False

    @database_sync_to_async
    def save_message(self, room_id, sender, content, message_type, file_url=None, file_type=None, file_size=0):
        try:
            room = ChatRoom.objects.get(id=room_id)
            if room.status != ChatRoom.RoomStatus.ACCEPTED:
                return None, 'REQUEST_PENDING'

            msg = Message.objects.create(
                chat_room=room,
                sender=sender,
                content=content,
                message_type=message_type,
                status=Message.MessageStatus.SENT,
            )

            if file_url and file_type:
                Attachment.objects.create(
                    message=msg,
                    file=file_url,
                    file_type=file_type,
                    size=file_size,
                )

            room.save(update_fields=['updated_at'])

            from .serializers import MessageSerializer
            return MessageSerializer(msg).data, None
        except Exception:
            return None, 'ERROR'

    @database_sync_to_async
    def mark_messages_as_read(self, room_id, reader_user):
        unread_msgs = Message.objects.filter(
            chat_room_id=room_id,
            status__in=[Message.MessageStatus.SENT, Message.MessageStatus.DELIVERED]
        ).exclude(sender=reader_user)

        read_ids = [str(m_id) for m_id in unread_msgs.values_list('id', flat=True)]
        if read_ids:
            unread_msgs.update(status=Message.MessageStatus.READ, read_at=timezone.now())
        return read_ids
