import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import Consultation, VoiceSession, VideoSession


class ConsultationCallConsumer(AsyncWebsocketConsumer):
    """
    WebSocket engine for Real-time Voice and Video Consultation Signaling (WebRTC / Agora).
    Route: ws/consultation/<consultation_id>/
    """

    async def connect(self):
        self.consultation_id = self.scope['url_route']['kwargs']['consultation_id']
        self.group_name = f'consultation_call_{self.consultation_id}'

        user = self.scope.get('user')
        if not user or user.is_anonymous:
            await self.close(code=4001)
            return

        is_member = await self.check_consultation_membership(user, self.consultation_id)
        if not is_member:
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except ValueError:
            return

        action_type = data.get('action')
        user = self.scope['user']

        # 1. Call Initiation (Ringing peer device)
        if action_type == 'call_offer':
            call_type = data.get('call_type', 'VOICE')  # VOICE or VIDEO
            sdp_offer = data.get('sdp_offer')
            rtc_token = data.get('rtc_token')

            await self.update_call_status(self.consultation_id, call_type, 'ONGOING')

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_offer',
                    'sender_id': str(user.id),
                    'sender_name': user.username,
                    'call_type': call_type,
                    'sdp_offer': sdp_offer,
                    'rtc_token': rtc_token,
                }
            )

        # 2. Call Answer (Accepting incoming call)
        elif action_type == 'call_answer':
            sdp_answer = data.get('sdp_answer')

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_answer',
                    'sender_id': str(user.id),
                    'sdp_answer': sdp_answer,
                }
            )

        # 3. ICE Candidate Packet Exchange
        elif action_type == 'ice_candidate':
            candidate = data.get('candidate')

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_ice_candidate',
                    'sender_id': str(user.id),
                    'candidate': candidate,
                }
            )

        # 4. Toggle Mute or Video state
        elif action_type == 'toggle_media':
            is_muted = data.get('is_muted')
            video_enabled = data.get('video_enabled')

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_media_toggle',
                    'sender_id': str(user.id),
                    'is_muted': is_muted,
                    'video_enabled': video_enabled,
                }
            )

        # 5. End Call
        elif action_type == 'end_call':
            call_type = data.get('call_type', 'VOICE')
            await self.update_call_status(self.consultation_id, call_type, 'ENDED')

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_ended',
                    'sender_id': str(user.id),
                    'ended_at': timezone.now().isoformat(),
                }
            )

    # Event Handlers for Broadcasting to Peer
    async def broadcast_call_offer(self, event):
        await self.send(text_data=json.dumps({
            'type': 'incoming_call_offer',
            'sender_id': event['sender_id'],
            'sender_name': event['sender_name'],
            'call_type': event['call_type'],
            'sdp_offer': event['sdp_offer'],
            'rtc_token': event['rtc_token'],
        }))

    async def broadcast_call_answer(self, event):
        await self.send(text_data=json.dumps({
            'type': 'call_answered',
            'sender_id': event['sender_id'],
            'sdp_answer': event['sdp_answer'],
        }))

    async def broadcast_ice_candidate(self, event):
        await self.send(text_data=json.dumps({
            'type': 'ice_candidate',
            'sender_id': event['sender_id'],
            'candidate': event['candidate'],
        }))

    async def broadcast_media_toggle(self, event):
        await self.send(text_data=json.dumps({
            'type': 'media_state_changed',
            'sender_id': event['sender_id'],
            'is_muted': event.get('is_muted'),
            'video_enabled': event.get('video_enabled'),
        }))

    async def broadcast_call_ended(self, event):
        await self.send(text_data=json.dumps({
            'type': 'call_ended',
            'sender_id': event['sender_id'],
            'ended_at': event['ended_at'],
        }))

    @database_sync_to_async
    def check_consultation_membership(self, user, consultation_id):
        try:
            consultation = Consultation.objects.get(id=consultation_id)
            if user == consultation.user or (hasattr(user, 'midwife_profile') and user.midwife_profile == consultation.midwife):
                return True
        except Consultation.DoesNotExist:
            pass
        return False

    @database_sync_to_async
    def update_call_status(self, consultation_id, call_type, status_val):
        try:
            consultation = Consultation.objects.get(id=consultation_id)
            now = timezone.now()

            if call_type == 'VOICE' and hasattr(consultation, 'voice_session'):
                session = consultation.voice_session
                session.status = status_val
                if status_val == 'ONGOING' and not session.started_at:
                    session.started_at = now
                elif status_val == 'ENDED':
                    session.ended_at = now
                session.save()

            elif call_type == 'VIDEO' and hasattr(consultation, 'video_session'):
                session = consultation.video_session
                session.status = status_val
                if status_val == 'ONGOING' and not session.started_at:
                    session.started_at = now
                elif status_val == 'ENDED':
                    session.ended_at = now
                session.save()

        except Consultation.DoesNotExist:
            pass
