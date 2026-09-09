import json
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import Consultation, VoiceSession, VideoSession
from .services import VoiceCallService
from apps.appointments.models import Appointment

logger = logging.getLogger(__name__)


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
            await self.process_call_service_action(self.consultation_id, user, 'START', call_type=call_type)

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
                            'action': 'INCOMING_CALL',
                            'consultation_id': self.consultation_id,
                            'sender_id': str(user.id),
                            'sender_name': sender_name,
                            'call_type': call_type,
                        }
                    }
                )

        # 2. Call Answered / Accepted
        elif action_type in ['call_accepted', 'call_answer', 'call_answered', 'incoming_call_answer', 'answer']:
            # NOTE: The HTTP /voice-session/accept/ endpoint is the authoritative
            # owner of the ACCEPT state transition.  When the Flutter client sends
            # call_accepted via the consultation room WS (fallback signal path) the
            # session is already ACCEPTED/ONGOING — calling process_call_service_action
            # here just produces an idempotent-repeat token generation on every
            # call_accepted relay.  Skip the service action; only relay the signal
            # to consultation room subscribers.
            call_type = data.get('call_type', 'VOICE')
            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_accepted',
                    'sender_id': str(user.id),
                    'consultation_id': self.consultation_id,
                }
            )

        # 3. Call Declined
        elif action_type in ['call_declined', 'decline', 'decline_call', 'call_decline']:
            call_type = data.get('call_type', 'VOICE')
            logger.info(f"[CALL] event=WS_DECLINE_RECEIVED consultation_id={self.consultation_id} user_id={user.id}")
            await self.process_call_service_action(self.consultation_id, user, 'DECLINE', call_type=call_type)

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_declined',
                    'sender_id': str(user.id),
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
                            'type': 'call_declined',
                            'action': 'CALL_DECLINED',
                            'consultation_id': self.consultation_id,
                            'sender_id': str(user.id),
                        }
                    }
                )

        # 4. Call Cancelled
        elif action_type in ['call_cancelled', 'cancel']:
            call_type = data.get('call_type', 'VOICE')
            await self.process_call_service_action(self.consultation_id, user, 'CANCEL', call_type=call_type)

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_cancelled',
                    'sender_id': str(user.id),
                    'consultation_id': self.consultation_id,
                }
            )

        # 5. Call Missed
        elif action_type in ['call_missed', 'missed']:
            call_type = data.get('call_type', 'VOICE')
            await self.process_call_service_action(self.consultation_id, user, 'MISSED', call_type=call_type)

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_missed',
                    'sender_id': str(user.id),
                    'consultation_id': self.consultation_id,
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
            await self.process_call_service_action(self.consultation_id, user, 'END', call_type=call_type)

            await self.channel_layer.group_send(
                self.group_name,
                {
                    'type': 'broadcast_call_ended',
                    'sender_id': str(user.id),
                    'ended_at': timezone.now().isoformat(),
                    'consultation_id': self.consultation_id,
                }
            )

    async def broadcast_incoming_call(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'incoming_call',
            'action': 'INCOMING_CALL',
            'sender_id': event['sender_id'],
            'sender_name': event.get('sender_name', ''),
            'call_type': event.get('call_type', 'VOICE'),
            'consultation_id': event.get('consultation_id', getattr(self, 'consultation_id', '')),
            'call_id': event.get('call_id', ''),
            'session_id': event.get('session_id', ''),
        }))

    async def broadcast_call_accepted(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'call_accepted',
            'action': 'CALL_ACCEPTED',
            'sender_id': event['sender_id'],
            'consultation_id': event.get('consultation_id', getattr(self, 'consultation_id', '')),
        }))

    async def broadcast_call_declined(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'call_declined',
            'action': 'CALL_DECLINED',
            'sender_id': event['sender_id'],
            'consultation_id': event.get('consultation_id', getattr(self, 'consultation_id', '')),
        }))

    async def broadcast_call_cancelled(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'call_cancelled',
            'action': 'CALL_CANCELLED',
            'sender_id': event['sender_id'],
            'consultation_id': event.get('consultation_id', getattr(self, 'consultation_id', '')),
        }))

    async def broadcast_call_missed(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'call_missed',
            'action': 'CALL_MISSED',
            'sender_id': event['sender_id'],
            'consultation_id': event.get('consultation_id', getattr(self, 'consultation_id', '')),
        }))

    async def broadcast_media_toggle(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'media_state_changed',
            'action': 'MEDIA_STATE_CHANGED',
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
            'action': 'CALL_ENDED',
            'sender_id': event['sender_id'],
            'ended_at': event.get('ended_at'),
            'consultation_id': event.get('consultation_id', getattr(self, 'consultation_id', '')),
        }))

    async def broadcast_peer_joined(self, event):
        user = self.scope.get('user')
        if user and str(event.get('sender_id')) == str(user.id):
            return
        await self.send(text_data=json.dumps({
            'type': 'peer_joined',
            'action': 'PEER_JOINED',
            'sender_id': event['sender_id'],
            'sender_name': event.get('sender_name', ''),
        }))

    @database_sync_to_async
    def process_call_service_action(self, consultation_id, user, action_name, call_type="VOICE"):
        try:
            consultation = Consultation.objects.filter(id=consultation_id).first()
            if not consultation:
                appointment = Appointment.objects.filter(id=consultation_id).first()
                if appointment and hasattr(appointment, 'consultation'):
                    consultation = appointment.consultation

            if not consultation:
                return

            if action_name == 'START':
                VoiceCallService.start_call(consultation, user, call_type=call_type, broadcast_ws=False)
            elif action_name == 'ACCEPT':
                VoiceCallService.accept_call(consultation, user, broadcast_ws=False)
            elif action_name == 'DECLINE':
                VoiceCallService.decline_call(consultation, user, broadcast_ws=False)
            elif action_name == 'CANCEL':
                VoiceCallService.cancel_call(consultation, user, broadcast_ws=False)
            elif action_name == 'MISSED':
                VoiceCallService.missed_call(consultation, user, broadcast_ws=False)
            elif action_name == 'END':
                VoiceCallService.end_call(consultation, user, broadcast_ws=False)
        except Exception as e:
            logger.error(f"[CALL] event=WS_ACTION_ERROR action={action_name} consultation_id={consultation_id} error={e}")

    @database_sync_to_async
    def get_recipient_user_id(self, consultation_id, user):
        try:
            consultation = Consultation.objects.filter(id=consultation_id).first()
            if not consultation:
                appointment = Appointment.objects.filter(id=consultation_id).first()
                if appointment and hasattr(appointment, 'consultation'):
                    consultation = appointment.consultation
            if not consultation:
                return None
            _, _, recipient = VoiceCallService.verify_and_resolve_participants(consultation, user)
            return str(recipient.id) if recipient else None
        except Exception:
            return None

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
        if not user or user.is_anonymous:
            return False
        try:
            consultation = Consultation.objects.filter(id=consultation_id).first()
            if not consultation:
                appointment = Appointment.objects.filter(id=consultation_id).first()
                if appointment:
                    consultation = getattr(appointment, 'consultation', None)

            if not consultation:
                return False

            is_patient = (str(user.id) == str(consultation.user_id))
            is_midwife = (
                (hasattr(user, 'midwife_profile') and consultation.midwife_id == user.midwife_profile.id) or
                (consultation.midwife and hasattr(consultation.midwife, 'user') and str(consultation.midwife.user_id) == str(user.id))
            )
            is_admin = user.is_staff or getattr(user, 'role', '') == 'ADMIN'

            return (is_patient or is_midwife or is_admin)
        except Exception as e:
            logger.error(f"[WS MEMBERSHIP CHECK ERROR] Failed for user {getattr(user, 'id', None)}: {e}")
            return False


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
        await self._deliver_user_call_signal(event)

    async def call_signal(self, event):
        await self._deliver_user_call_signal(event)

    async def call_declined(self, event):
        await self._deliver_user_call_signal(event)

    async def call_ended(self, event):
        await self._deliver_user_call_signal(event)

    async def call_cancelled(self, event):
        await self._deliver_user_call_signal(event)

    async def call_accepted(self, event):
        await self._deliver_user_call_signal(event)

    async def call_offer(self, event):
        await self._deliver_user_call_signal(event)

    async def incoming_call(self, event):
        await self._deliver_user_call_signal(event)

    async def _deliver_user_call_signal(self, data_or_event):
        if not isinstance(data_or_event, dict):
            return

        data = data_or_event.get('data') if isinstance(data_or_event.get('data'), dict) else data_or_event

        user = self.scope.get('user')
        sender_id = str(data.get('caller_id') or data.get('sender_id') or data_or_event.get('sender_id') or '')
        user_id_str = str(getattr(user, 'id', ''))
        if user and sender_id and sender_id == user_id_str:
            return  # Strictly ignore self-call notification

        action = data.get('action') or data.get('type') or data_or_event.get('action') or data_or_event.get('type') or 'call_offer'
        call_id = data.get('call_id') or data.get('session_id') or data.get('session_key') or data_or_event.get('call_id') or ''

        action_log = action.upper()
        if 'ACCEPT' in action_log:
            action_log = 'ACCEPT'
        elif 'DECLINE' in action_log or 'REJECT' in action_log:
            action_log = 'DECLINE'
        elif 'END' in action_log or 'CANCEL' in action_log:
            action_log = 'END'

        logger.info(f"[CALL-ACTION] source=WEBSOCKET action={action_log} event=SIGNAL_DELIVERED call_id={call_id} user_id={user_id_str}")
        logger.info(f"[WS] event=CALL_SIGNAL_DELIVERED user={user_id_str} action={action} call_id={call_id}")

        payload = {
            "action": action,
            "event": data.get("event", action),
            "call_id": call_id,
            "session_id": call_id,
            "session_key": call_id,
            "consultation_id": str(data.get("consultation_id", "") or data_or_event.get("consultation_id", "")),
            "appointment_id": str(data.get("appointment_id", "") or data_or_event.get("appointment_id", "")),
            "caller_id": sender_id,
            "receiver_id": str(data.get("receiver_id") or data.get("recipient_id") or user_id_str),
            "recipient_id": str(data.get("recipient_id") or data.get("receiver_id") or user_id_str),
            "caller_name": data.get("caller_name") or data.get("sender_name") or "Caller",
            "receiver_name": data.get("receiver_name") or data.get("recipient_name") or "",
            "recipient_name": data.get("recipient_name") or data.get("receiver_name") or "",
            "call_type": data.get("call_type", "VOICE"),
            "agora_channel_name": data.get("agora_channel_name") or "",
            "agora_app_id": data.get("agora_app_id") or "",
            "timestamp": data.get("timestamp") or str(int(timezone.now().timestamp())),
        }
        if "status" in data or "status" in data_or_event:
            payload["status"] = data.get("status") or data_or_event.get("status")
        if "ended_at" in data or "ended_at" in data_or_event:
            payload["ended_at"] = data.get("ended_at") or data_or_event.get("ended_at")

        await self.send(text_data=json.dumps(payload))


