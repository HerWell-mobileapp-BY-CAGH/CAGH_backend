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
        raw_id = self.scope['url_route']['kwargs']['consultation_id']
        user = self.scope.get('user')
        if not user or user.is_anonymous:
            await self.close(code=4001)
            return

        self.consultation_id = await self.get_canonical_consultation_id(raw_id)
        self.group_name = f'consultation_call_{self.consultation_id}'

        is_member = await self.check_consultation_membership(user, self.consultation_id)
        if not is_member:
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

        sender_name = getattr(user, 'full_name', None) or getattr(user, 'username', None) or str(user)
        await self.channel_layer.group_send(
            self.group_name,
            {
                'type': 'broadcast_peer_joined',
                'sender_id': str(user.id),
                'sender_name': sender_name,
            }
        )

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            try:
                await self.channel_layer.group_discard(
                    self.group_name,
                    self.channel_name
                )
            except Exception:
                pass

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except ValueError:
            return

        action_type = data.get('action') or data.get('type')
        user = self.scope['user']
        sender_name = getattr(user, 'full_name', None) or getattr(user, 'username', None) or str(user)

        if action_type == 'ping':
            await self.send(text_data=json.dumps({'type': 'pong'}))
            return

        # 1. Call Initiation (Ringing peer device)
        if action_type in ['call_offer', 'incoming_call_offer', 'offer']:
            call_type = data.get('call_type', 'VOICE')  # VOICE or VIDEO
            sdp_offer = data.get('sdp_offer') or data.get('sdp') or data.get('offer')
            rtc_token = data.get('rtc_token')

            await self.update_call_status(self.consultation_id, call_type, 'ONGOING')

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_offer',
                    'sender_id': str(user.id),
                    'sender_name': sender_name,
                    'call_type': call_type,
                    'sdp_offer': sdp_offer,
                    'rtc_token': rtc_token,
                    'consultation_id': self.consultation_id,
                }
            )

            recipient_id = await self.get_recipient_user_id(self.consultation_id, user)
            if recipient_id:
                await self.channel_layer.group_send(
                    f"user_calls_{recipient_id}",
                    {
                        'type': 'broadcast_incoming_call',
                        'data': {
                            'type': 'incoming_call_offer',
                            'action': 'incoming_call_offer',
                            'consultation_id': self.consultation_id,
                            'sender_id': str(user.id),
                            'sender_name': sender_name,
                            'call_type': call_type,
                            'sdp_offer': sdp_offer,
                            'rtc_token': rtc_token,
                        }
                    }
                )

        # 2. Call Answer (Accepting incoming call)
        elif action_type in ['call_answer', 'call_answered', 'incoming_call_answer', 'answer']:
            sdp_answer = data.get('sdp_answer') or data.get('sdp') or data.get('answer')

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_answer',
                    'sender_id': str(user.id),
                    'sdp_answer': sdp_answer,
                }
            )

        # 3. ICE Candidate Packet Exchange
        elif action_type in ['ice_candidate', 'candidate']:
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
        elif action_type in ['end_call', 'call_ended']:
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

    # Event Handlers for Broadcasting to Peer (Skips sending back to the sender)
    async def broadcast_call_offer(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'incoming_call_offer',
            'action': 'incoming_call_offer',
            'sender_id': event['sender_id'],
            'sender_name': event['sender_name'],
            'call_type': event['call_type'],
            'sdp_offer': event['sdp_offer'],
            'rtc_token': event.get('rtc_token'),
            'consultation_id': event.get('consultation_id', self.consultation_id),
        }))

    async def broadcast_call_answer(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'call_answered',
            'action': 'call_answered',
            'sender_id': event['sender_id'],
            'sdp_answer': event['sdp_answer'],
        }))

    async def broadcast_ice_candidate(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'ice_candidate',
            'action': 'ice_candidate',
            'sender_id': event['sender_id'],
            'candidate': event['candidate'],
        }))

    async def broadcast_media_toggle(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'media_state_changed',
            'action': 'media_state_changed',
            'sender_id': event['sender_id'],
            'is_muted': event.get('is_muted'),
            'video_enabled': event.get('video_enabled'),
        }))

    async def broadcast_call_ended(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'call_ended',
            'action': 'call_ended',
            'sender_id': event['sender_id'],
            'ended_at': event['ended_at'],
        }))

    async def broadcast_peer_joined(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'peer_joined',
            'action': 'peer_joined',
            'sender_id': event['sender_id'],
            'sender_name': event['sender_name'],
        }))

    @database_sync_to_async
    def get_canonical_consultation_id(self, raw_id):
        try:
            consultation = Consultation.objects.filter(id=raw_id).first()
            if consultation:
                return str(consultation.id)

            appointment = Appointment.objects.filter(id=raw_id).first()
            if appointment:
                consultation = getattr(appointment, 'consultation', None)
                if not consultation:
                    consultation, _ = Consultation.objects.get_or_create(
                        appointment=appointment,
                        defaults={
                            'user': appointment.user,
                            'midwife': appointment.midwife,
                            'consultation_type': appointment.appointment_type,
                            'status': Consultation.ConsultationStatus.SCHEDULED,
                        }
                    )
                return str(consultation.id)
        except Exception:
            pass
        return str(raw_id)

    @database_sync_to_async
    def check_consultation_membership(self, user, consultation_id):
        try:
            consultation = Consultation.objects.filter(id=consultation_id).first()
            if not consultation:
                appointment = Appointment.objects.filter(id=consultation_id).first()
                if appointment:
                    consultation = getattr(appointment, 'consultation', None)
                    if not consultation:
                        consultation, _ = Consultation.objects.get_or_create(
                            appointment=appointment,
                            defaults={
                                'user': appointment.user,
                                'midwife': appointment.midwife,
                                'consultation_type': appointment.appointment_type,
                                'status': Consultation.ConsultationStatus.SCHEDULED,
                            }
                        )
            if not consultation:
                return True

            if str(user.id) == str(consultation.user_id):
                return True
            if getattr(user, 'role', '') == 'MIDWIFE' or hasattr(user, 'midwife_profile'):
                if not consultation.midwife or consultation.midwife == getattr(user, 'midwife_profile', None):
                    return True
            if user.is_staff or getattr(user, 'role', '') == 'ADMIN':
                return True
        except Exception:
            pass
        return True

    @database_sync_to_async
    def update_call_status(self, consultation_id, call_type, status_val):
        try:
            consultation = Consultation.objects.filter(id=consultation_id).first()
            if not consultation:
                appointment = Appointment.objects.filter(id=consultation_id).first()
                if appointment and hasattr(appointment, 'consultation'):
                    consultation = appointment.consultation

            if not consultation:
                return

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

        except Exception:
            pass

    @database_sync_to_async
    def get_recipient_user_id(self, consultation_id, sender_user):
        try:
            from apps.appointments.models import Appointment
            sender_id = str(getattr(sender_user, 'id', ''))

            consultation = Consultation.objects.filter(id=consultation_id).first()
            if not consultation:
                appointment = Appointment.objects.filter(id=consultation_id).first()
                if appointment:
                    patient_id = str(appointment.user.id) if appointment.user else ''
                    midwife_user_id = str(appointment.midwife.user.id) if (appointment.midwife and hasattr(appointment.midwife, 'user') and appointment.midwife.user) else ''
                    if sender_id == patient_id:
                        return midwife_user_id
                    else:
                        return patient_id
            elif consultation:
                patient_id = str(consultation.user.id) if consultation.user else ''
                midwife_user_id = str(consultation.midwife.user.id) if (consultation.midwife and hasattr(consultation.midwife, 'user') and consultation.midwife.user) else ''
                if sender_id == patient_id:
                    return midwife_user_id
                else:
                    return patient_id
        except Exception as e:
            print(f"Error in get_recipient_user_id: {e}")
        return None


class UserCallConsumer(AsyncWebsocketConsumer):
    """
    Persistent background WebSocket consumer for user call signaling (ws/user-calls/).
    Rings incoming calls across all tabs and screens.
    """

    async def connect(self):
        user = self.scope.get('user')
        if not user or user.is_anonymous:
            await self.close(code=4001)
            return

        self.user_group = f"user_calls_{user.id}"
        await self.channel_layer.group_add(
            self.user_group,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'user_group'):
            try:
                await self.channel_layer.group_discard(
                    self.user_group,
                    self.channel_name
                )
            except Exception:
                pass

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            action = data.get('type') or data.get('action')
            if action == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
        except Exception:
            pass

    async def broadcast_incoming_call(self, event):
        await self.send(text_data=json.dumps(event['data']))
