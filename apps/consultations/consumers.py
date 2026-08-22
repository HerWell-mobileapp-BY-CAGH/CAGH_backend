import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import Consultation, VoiceSession, VideoSession


class ConsultationCallConsumer(AsyncWebsocketConsumer):
    """
    WebSocket engine for Real-time Call State Signaling (Agora Audio / Call Lifecycle).
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

        # 1. Call Initiation / Ringing Alert
        if action_type in ['incoming_call', 'call_offer', 'incoming_call_offer', 'offer', 'call_initiated']:
            call_type = data.get('call_type', 'VOICE')

            await self.update_call_status(self.consultation_id, call_type, 'RINGING', caller_user=user)

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_incoming_call',
                    'sender_id': str(user.id),
                    'sender_name': sender_name,
                    'call_type': call_type,
                    'consultation_id': self.consultation_id,
                }
            )

            recipient_id = await self.get_recipient_user_id(self.consultation_id, user)
            if recipient_id:
                await self.channel_layer.group_send(
                    f"user_calls_{recipient_id}",
                    {
                        'type': 'broadcast_user_incoming_call',
                        'data': {
                            'type': 'incoming_call',
                            'action': 'incoming_call',
                            'consultation_id': self.consultation_id,
                            'sender_id': str(user.id),
                            'sender_name': sender_name,
                            'call_type': call_type,
                        }
                    }
                )

        # 2. Call Answered / Accepted
        elif action_type in ['call_accepted', 'call_answer', 'call_answered', 'incoming_call_answer', 'answer']:
            call_type = data.get('call_type', 'VOICE')
            await self.update_call_status(self.consultation_id, call_type, 'ACCEPTED')

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_accepted',
                    'sender_id': str(user.id),
                }
            )

        # 3. Call Declined
        elif action_type in ['call_declined', 'decline']:
            call_type = data.get('call_type', 'VOICE')
            await self.update_call_status(self.consultation_id, call_type, 'DECLINED')

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_declined',
                    'sender_id': str(user.id),
                }
            )

        # 4. Call Cancelled
        elif action_type in ['call_cancelled', 'cancel']:
            call_type = data.get('call_type', 'VOICE')
            await self.update_call_status(self.consultation_id, call_type, 'CANCELLED')

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_cancelled',
                    'sender_id': str(user.id),
                }
            )

        # 5. Call Missed
        elif action_type in ['call_missed', 'missed']:
            call_type = data.get('call_type', 'VOICE')
            await self.update_call_status(self.consultation_id, call_type, 'MISSED')

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_missed',
                    'sender_id': str(user.id),
                }
            )

        # 6. Toggle Media Mute state
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

        # 7. End Call
        elif action_type in ['call_ended', 'end_call']:
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

    async def broadcast_incoming_call(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'incoming_call',
            'action': 'incoming_call',
            'sender_id': event['sender_id'],
            'sender_name': event['sender_name'],
            'call_type': event['call_type'],
            'consultation_id': event.get('consultation_id', self.consultation_id),
        }))

    async def broadcast_call_accepted(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'call_accepted',
            'action': 'call_accepted',
            'sender_id': event['sender_id'],
        }))

    async def broadcast_call_declined(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'call_declined',
            'action': 'call_declined',
            'sender_id': event['sender_id'],
        }))

    async def broadcast_call_cancelled(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'call_cancelled',
            'action': 'call_cancelled',
            'sender_id': event['sender_id'],
        }))

    async def broadcast_call_missed(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'call_missed',
            'action': 'call_missed',
            'sender_id': event['sender_id'],
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
    def update_call_status(self, consultation_id, call_type, status_val, caller_user=None):
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
                if caller_user and not session.caller:
                    session.caller = caller_user
                if status_val in ['ACCEPTED', 'ONGOING'] and not session.started_at:
                    session.started_at = now
                elif status_val in ['ENDED', 'DECLINED', 'CANCELLED', 'MISSED']:
                    session.ended_at = now
                session.save()

            elif call_type == 'VIDEO' and hasattr(consultation, 'video_session'):
                session = consultation.video_session
                session.status = status_val
                if status_val in ['ACCEPTED', 'ONGOING'] and not session.started_at:
                    session.started_at = now
                elif status_val in ['ENDED', 'DECLINED', 'CANCELLED', 'MISSED']:
                    session.ended_at = now
                session.save()

        except Exception:
            pass

    @database_sync_to_async
    def get_recipient_user_id(self, consultation_id, sender_user):
        try:
            sender_id = str(getattr(sender_user, 'id', ''))

            patient_id = ''
            midwife_user_id = ''

            consultation = Consultation.objects.filter(id=consultation_id).first()
            if not consultation:
                appointment = Appointment.objects.filter(id=consultation_id).first()
                if appointment:
                    patient_id = str(appointment.user.id) if appointment.user else ''
                    midwife_user_id = str(appointment.midwife.user.id) if (appointment.midwife and hasattr(appointment.midwife, 'user') and appointment.midwife.user) else ''
            else:
                patient_id = str(consultation.user.id) if consultation.user else ''
                midwife_user_id = str(consultation.midwife.user.id) if (consultation.midwife and hasattr(consultation.midwife, 'user') and consultation.midwife.user) else ''

            recipient_id = midwife_user_id if sender_id == patient_id else patient_id
            if recipient_id and recipient_id != sender_id:
                return recipient_id
        except Exception:
            pass
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

    async def broadcast_user_incoming_call(self, event):
        user = self.scope.get('user')
        data = event.get('data', {})
        sender_id = str(data.get('sender_id', ''))
        if user and sender_id and sender_id == str(user.id):
            return  # Strictly ignore self-call notification
        await self.send(text_data=json.dumps(data))

