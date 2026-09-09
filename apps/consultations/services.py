import uuid
import logging
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from rest_framework.exceptions import PermissionDenied, ValidationError

from .models import Consultation, VoiceSession
from .agora_service import AgoraService, Role as AgoraRole
from apps.notifications.call_notifications import send_incoming_call_notification

logger = logging.getLogger(__name__)

RINGING_TIMEOUT_SECONDS = getattr(settings, 'VOICE_CALL_RINGING_TIMEOUT_SECONDS', 45)
TERMINAL_CALL_STATES = [
    VoiceSession.VoiceSessionStatus.CANCELLED,
    VoiceSession.VoiceSessionStatus.DECLINED,
    VoiceSession.VoiceSessionStatus.MISSED,
    VoiceSession.VoiceSessionStatus.ENDED,
    VoiceSession.VoiceSessionStatus.FAILED,
]


class VoiceCallService:
    """
    Single Authoritative Call-Management Service.
    Responsible for:
    - Participant resolution & identity verification
    - Atomic state machine transitions with database row locking
    - Idempotency for decline, cancel, missed, end
    - Reusing active non-terminal sessions (duplicate start prevention)
    - Transactionally safe FCM notification dispatch
    - Agora RTC session and token authorization
    - Django Channels WebSocket signaling broadcasts
    """

    @staticmethod
    def get_display_name(u):
        if not u:
            return ""
        if hasattr(u, 'profile') and u.profile:
            fn = getattr(u.profile, 'first_name', '').strip()
            ln = getattr(u.profile, 'last_name', '').strip()
            if fn or ln:
                return f"{fn} {ln}".strip()
        if hasattr(u, 'first_name') and (getattr(u, 'first_name', '') or getattr(u, 'last_name', '')):
            fn = getattr(u, 'first_name', '').strip()
            ln = getattr(u, 'last_name', '').strip()
            if fn or ln:
                return f"{fn} {ln}".strip()
        return getattr(u, 'username', '')

    @classmethod
    def verify_and_resolve_participants(cls, consultation: Consultation, user):
        """
        Validates user participation and resolves caller and recipient User model instances.
        Enforces caller_id != receiver_id.
        Returns (is_patient, is_midwife, recipient_user)
        """
        user_id_str = str(user.id)
        patient_id_str = str(consultation.user_id) if consultation.user else ""

        midwife_user = None
        midwife_user_id_str = ""
        if consultation.midwife and hasattr(consultation.midwife, 'user') and consultation.midwife.user:
            midwife_user = consultation.midwife.user
            midwife_user_id_str = str(midwife_user.id)

        is_patient = (user_id_str == patient_id_str)
        is_midwife = (
            (hasattr(user, 'midwife_profile') and consultation.midwife_id == user.midwife_profile.id) or
            (midwife_user_id_str != "" and user_id_str == midwife_user_id_str)
        )
        is_admin = user.is_staff or getattr(user, 'role', '') == 'ADMIN'

        if not (is_patient or is_midwife or is_admin):
            logger.warning(f"[CALL] event=UNAUTHORIZED_ATTEMPT consultation_id={consultation.id} user_id={user.id}")
            raise PermissionDenied("You are not authorized to participate in this consultation call.")

        recipient = None
        if is_midwife:
            recipient = consultation.user
        else:
            recipient = midwife_user

        if recipient and str(recipient.id) == user_id_str:
            logger.info(f"[CALL] event=SELF_CALL_REJECTED caller={user_id_str} receiver={user_id_str}")
            raise ValidationError({"error": "Self-calling is prohibited. Caller and receiver cannot be the same user."})

        if not recipient:
            logger.info(f"[CALL] event=SELF_CALL_REJECTED caller={user_id_str} receiver=None")
            raise ValidationError({"error": "No valid recipient found for this consultation call."})

        return is_patient, is_midwife, recipient

    @classmethod
    def check_and_auto_expire_ringing_session(cls, session: VoiceSession):
        """
        Auto-expires a ringing call if no response within RINGING_TIMEOUT_SECONDS.
        """
        if session and session.status == VoiceSession.VoiceSessionStatus.RINGING:
            reference_time = getattr(session, 'updated_at', None) or session.started_at or (session.consultation.updated_at if session.consultation else None)
            if reference_time and (timezone.now() - reference_time) > timedelta(seconds=RINGING_TIMEOUT_SECONDS):
                session.status = VoiceSession.VoiceSessionStatus.MISSED
                session.ended_at = timezone.now()
                session.save(update_fields=['status', 'ended_at'])
                logger.info(f"[CALL] call_id={session.session_key} event=AUTO_EXPIRED_RINGING_TIMEOUT")

    @classmethod
    def broadcast_call_status(cls, consultation: Consultation, session: VoiceSession, user, action_type: str, ended_at=None):
        """
        Broadcasts call signaling status changes via Django Channels WebSockets to consultation and target user channels.
        """
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            if not channel_layer:
                return

            action_lower = action_type.lower()
            event_type = f"broadcast_call_{action_lower}"
            event_name = f"call_{action_lower}"
            user_id_str = str(user.id)

            ws_payload = {
                'type': event_name,
                'action': event_name,
                'event': event_name,
                'status': action_type,
                'sender_id': user_id_str,
                'caller_id': user_id_str,
                'consultation_id': str(consultation.id),
                'session_id': session.session_key if session else "",
                'call_id': session.session_key if session else "",
            }
            if ended_at:
                ws_payload['ended_at'] = ended_at.isoformat() if hasattr(ended_at, 'isoformat') else ended_at

            # Point-to-point call lifecycle signals (ACCEPTED, DECLINED, ENDED,
            # CANCELLED) must only be delivered to the target user's personal
            # channel.  Broadcasting to the consultation room group as well
            # causes duplicate delivery when the caller is subscribed to both
            # the user_calls channel and the consultation room channel.
            ROOM_BROADCAST_ACTIONS = {'incoming', 'offer', 'connected'}
            should_broadcast_to_room = action_lower in ROOM_BROADCAST_ACTIONS

            if should_broadcast_to_room:
                async_to_sync(channel_layer.group_send)(
                    f"consultation_call_{consultation.id}",
                    {
                        'type': event_type,
                        'action': event_name,
                        'sender_id': user_id_str,
                        'consultation_id': str(consultation.id),
                        'ended_at': ws_payload.get('ended_at'),
                    }
                )

            recipient_id = None
            if session and session.caller and str(session.caller.id) != user_id_str:
                recipient_id = str(session.caller.id)
            else:
                patient_id = str(consultation.user.id) if consultation.user else ""
                midwife_user_id = str(consultation.midwife.user.id) if (consultation.midwife and hasattr(consultation.midwife, 'user') and consultation.midwife.user) else ""

                if user_id_str == patient_id and midwife_user_id:
                    recipient_id = midwife_user_id
                elif user_id_str == midwife_user_id and patient_id:
                    recipient_id = patient_id

            if recipient_id and recipient_id != user_id_str:
                ws_payload['receiver_id'] = recipient_id
                ws_payload['recipient_id'] = recipient_id
                signal_data = dict(ws_payload)
                signal_data['type'] = 'call_signal'
                signal_data['action'] = event_name
                signal_data['event'] = event_name
                signal_data['data'] = ws_payload

                action_log_name = action_type.upper()
                if action_log_name in ['ACCEPTED', 'ACCEPT']:
                    action_log_name = 'ACCEPT'
                elif action_log_name in ['DECLINED', 'DECLINE']:
                    action_log_name = 'DECLINE'
                elif action_log_name in ['ENDED', 'END']:
                    action_log_name = 'END'

                logger.info(f"[CALL-ACTION] source=WEBSOCKET action={action_log_name} event=SIGNAL_DISPATCHING call_id={getattr(session, 'session_key', None)} recipient={recipient_id}")
                async_to_sync(channel_layer.group_send)(
                    f"user_calls_{recipient_id}",
                    signal_data
                )
                logger.info(f"[CALL-ACTION] source=WEBSOCKET action={action_log_name} event=SIGNAL_DISPATCHED call_id={getattr(session, 'session_key', None)} recipient={recipient_id}")
                logger.info(f"[CALL] call_id={getattr(session, 'session_key', None)} event=WS_USER_SIGNAL_SENT recipient={recipient_id} action={event_name}")
        except Exception as e:
            logger.error(f"[CALL] event=WS_BROADCAST_ERROR action={action_type} error={e}")

    @classmethod
    def get_voice_session(cls, consultation: Consultation, select_for_update=False) -> VoiceSession:
        qs = VoiceSession.objects.filter(consultation=consultation)
        if select_for_update:
            qs = qs.select_for_update()

        active = qs.exclude(status__in=TERMINAL_CALL_STATES).order_by('-created_at').first()
        if active:
            return active

        return qs.order_by('-created_at').first()

    @classmethod
    def start_call(cls, consultation: Consultation, caller, call_type="VOICE", broadcast_ws=True) -> dict:
        """
        Starts or reuses a VoiceSession.
        Prevents duplicate start & duplicate FCM push.
        Atomically locks session in DB transaction.
        """
        if consultation.status == Consultation.ConsultationStatus.COMPLETED:
            raise ValidationError({"error": "Completed consultations cannot be restarted."})

        with transaction.atomic():
            is_patient, is_midwife, recipient = cls.verify_and_resolve_participants(consultation, caller)

            consultation.status = Consultation.ConsultationStatus.ACTIVE
            consultation.save(update_fields=['status'])

            active_session = VoiceSession.objects.select_for_update().filter(
                consultation=consultation
            ).exclude(status__in=TERMINAL_CALL_STATES).order_by('-created_at').first()

            if active_session:
                cls.check_and_auto_expire_ringing_session(active_session)
                # Refresh status post-expire check
                if active_session.status in TERMINAL_CALL_STATES:
                    active_session = None

            if active_session:
                session = active_session
                session_key = session.session_key
                agora_channel_name = session.agora_channel_name
                is_new_call_attempt = False
                logger.info(f"[CALL] call_id={session_key} event=REUSING_ACTIVE_SESSION status={session.status}")
            else:
                session_key = f"VOICE-{uuid.uuid4().hex[:12].upper()}"
                agora_channel_name = f"cagh_voice_{session_key}"
                session = VoiceSession.objects.create(
                    consultation=consultation,
                    session_key=session_key,
                    agora_channel_name=agora_channel_name,
                    status=VoiceSession.VoiceSessionStatus.RINGING,
                    caller=caller,
                )
                is_new_call_attempt = True
                logger.info(f"[CALL] call_id={session_key} event=VOICE_SESSION_CREATED caller={caller.id} receiver={getattr(recipient, 'id', None)}")

        caller_name = cls.get_display_name(caller) or getattr(caller, 'username', 'Caller')
        recipient_name = cls.get_display_name(recipient) or getattr(recipient, 'username', 'Recipient')
        agora_app_id = getattr(settings, 'AGORA_APP_ID', 'cagh_agora_app_id_placeholder')

        # 1. Authoritative WebSocket Call Offer Dispatch (Independent of FCM)
        if broadcast_ws and recipient and is_new_call_attempt:
            group_name = f"user_calls_{recipient.id}"
            logger.info(
                f"[CALL] call_id={session_key} event=WS_CALL_OFFER_DISPATCHING receiver={recipient.id} group={group_name}"
            )
            try:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                channel_layer = get_channel_layer()
                if channel_layer:
                    ws_payload = {
                        "type": "call_signal",
                        "action": "call_offer",
                        "event": "VOICE_SESSION_CREATED",
                        "call_id": session_key,
                        "session_id": session_key,
                        "session_key": session_key,
                        "consultation_id": str(consultation.id),
                        "appointment_id": str(consultation.appointment.id) if consultation.appointment else str(consultation.id),
                        "caller_id": str(caller.id),
                        "receiver_id": str(recipient.id),
                        "recipient_id": str(recipient.id),
                        "caller_name": caller_name,
                        "receiver_name": recipient_name,
                        "recipient_name": recipient_name,
                        "call_type": call_type,
                        "agora_channel_name": agora_channel_name,
                        "agora_app_id": agora_app_id,
                        "timestamp": str(int(timezone.now().timestamp())),
                    }
                    async_to_sync(channel_layer.group_send)(
                        group_name,
                        ws_payload
                    )
                    logger.info(
                        f"[CALL] call_id={session_key} event=WS_CALL_OFFER_SENT recipient={recipient.id} action=call_offer"
                    )
                    async_to_sync(channel_layer.group_send)(
                        f"consultation_call_{consultation.id}",
                        {
                            'type': 'broadcast_incoming_call',
                            'sender_id': str(caller.id),
                            'sender_name': caller_name,
                            'call_type': call_type,
                            'consultation_id': str(consultation.id),
                            'session_id': session_key,
                            'call_id': session_key,
                        }
                    )
            except Exception:
                logger.exception(
                    f"[CALL] call_id={session_key} event=WS_CALL_OFFER_FAILED recipient={recipient.id}"
                )

        # 2. Schedule Celery background ringing timeout execution & FCM dispatch
        if is_new_call_attempt:
            import sys
            if 'test' not in sys.argv and not getattr(settings, 'CELERY_TASK_ALWAYS_EAGER', False):
                try:
                    from .tasks import check_and_expire_ringing_session_task
                    check_and_expire_ringing_session_task.apply_async(
                        args=[str(session.id)],
                        countdown=RINGING_TIMEOUT_SECONDS + 1
                    )
                except Exception as te:
                    logger.debug(f"[CALL] Celery task scheduling skipped: {te}")

            if recipient:
                try:
                    send_incoming_call_notification(
                        caller=caller,
                        recipient=recipient,
                        consultation=consultation,
                        call_type=call_type,
                        session_key=session_key,
                        agora_channel_name=agora_channel_name,
                        agora_app_id=agora_app_id,
                    )
                except Exception as e:
                    logger.error(f"[CALL] call_id={session_key} event=FCM_NOTIFICATION_ERROR error={e}")

        agora_token = AgoraService.generate_rtc_token(
            channel_name=agora_channel_name,
            uid=caller.id,
            role=AgoraRole.PUBLISHER
        )

        return {
            'status': session.status,
            'started_at': session.started_at,
            'call_type': call_type,
            'session_key': session_key,
            'call_id': session_key,
            'agora_channel_name': agora_channel_name,
            'agora_app_id': agora_app_id,
            'agora_token': agora_token,
            'uid': AgoraService.get_numeric_uid(caller.id),
            'caller_id': str(caller.id),
            'caller_name': caller_name,
            'receiver_id': str(recipient.id) if recipient else "",
            'recipient_id': str(recipient.id) if recipient else "",
            'receiver_name': recipient_name,
            'recipient_name': recipient_name,
            'consultation_id': str(consultation.id),
        }

    @classmethod
    def accept_call(cls, consultation: Consultation, user, broadcast_ws=True) -> tuple[dict, int]:
        """
        Accepts an active ringing VoiceSession.
        Enforces database locking and rejects illegal state transitions with 409 Conflict.
        Handles repeated ACCEPT requests idempotently without duplicate side-effects.
        """
        is_idempotent_repeat = False
        with transaction.atomic():
            cls.verify_and_resolve_participants(consultation, user)
            session = cls.get_voice_session(consultation, select_for_update=True)
            if not session:
                return {"error": "No voice session found to accept."}, 404

            cls.check_and_auto_expire_ringing_session(session)

            if session.status in TERMINAL_CALL_STATES:
                logger.warning(f"[CALL] call_id={session.session_key} event=ACCEPT_REJECTED status={session.status}")
                return {"error": f"Cannot accept call. Call status is '{session.status}'."}, 409

            if session.status in [VoiceSession.VoiceSessionStatus.ACCEPTED, VoiceSession.VoiceSessionStatus.ONGOING]:
                is_idempotent_repeat = True
                logger.info(f"[CALL-ACTION] action=ACCEPT event=IDEMPOTENT_ACCEPT_REPEAT call_id={session.session_key} status={session.status} user_id={user.id}")
                logger.info(f"[CALL] call_id={session.session_key} event=IDEMPOTENT_ACCEPT_REPEAT status={session.status} user_id={user.id}")
            else:
                old_status = session.status
                session.status = VoiceSession.VoiceSessionStatus.ACCEPTED
                if not session.started_at:
                    session.started_at = timezone.now()
                if not session.agora_channel_name:
                    session.agora_channel_name = f"cagh_voice_{session.session_key}"
                session.save()

                consultation.status = Consultation.ConsultationStatus.ACTIVE
                if not consultation.started_at:
                    consultation.started_at = timezone.now()
                consultation.save()

                logger.info(f"[CALL-ACTION] action=ACCEPT event=STATE_TRANSITION call_id={session.session_key} from={old_status} to={session.status} user_id={user.id}")
                logger.info(f"[CALL] call_id={session.session_key} event=CALL_ACCEPTED user_id={user.id}")

        if broadcast_ws and not is_idempotent_repeat:
            cls.broadcast_call_status(consultation, session, user, 'ACCEPTED')

        agora_app_id = getattr(settings, 'AGORA_APP_ID', 'cagh_agora_app_id_placeholder')
        caller = session.caller
        _, _, recipient = cls.verify_and_resolve_participants(consultation, user)
        caller_name = cls.get_display_name(caller) or getattr(caller, 'username', 'Caller')
        recipient_name = cls.get_display_name(recipient) or getattr(recipient, 'username', 'Recipient')

        # Only call the token builder for genuine accepts.
        # Idempotent repeats (duplicate ACCEPT from CallKit echo, cold-start
        # restore, etc.) still receive a valid token so the response is
        # always usable, but we skip the unnecessary extra RtcTokenBuilder
        # invocation to avoid the triple token-generation log noise.
        if not is_idempotent_repeat:
            token = AgoraService.generate_rtc_token(
                channel_name=session.agora_channel_name,
                uid=user.id,
                role=AgoraRole.PUBLISHER
            )
        else:
            # Re-generate once on idempotent repeat so the caller still gets
            # a valid token, but log clearly that this is a repeat path.
            logger.info(
                f"[CALL] call_id={session.session_key} event=ACCEPT_TOKEN_REPEAT_GEN "
                f"user_id={user.id} — generating token for idempotent repeat"
            )
            token = AgoraService.generate_rtc_token(
                channel_name=session.agora_channel_name,
                uid=user.id,
                role=AgoraRole.PUBLISHER
            )

        return {
            'status': session.status,
            'session_key': session.session_key,
            'call_id': session.session_key,
            'agora_channel_name': session.agora_channel_name,
            'agora_app_id': agora_app_id,
            'agora_token': token,
            'uid': AgoraService.get_numeric_uid(user.id),
            'started_at': session.started_at,
            'caller_id': str(caller.id) if caller else "",
            'caller_name': caller_name,
            'receiver_id': str(recipient.id) if recipient else "",
            'recipient_id': str(recipient.id) if recipient else "",
            'receiver_name': recipient_name,
            'recipient_name': recipient_name,
            'consultation_id': str(consultation.id),
        }, 200

    @classmethod
    def connect_call(cls, consultation: Consultation, user, broadcast_ws=True) -> tuple[dict, int]:
        """
        Marks call ONGOING/ACTIVE when Agora audio connects.
        """
        with transaction.atomic():
            cls.verify_and_resolve_participants(consultation, user)
            session = cls.get_voice_session(consultation, select_for_update=True)
            if not session:
                return {"error": "No voice session found."}, 404

            if session.status in TERMINAL_CALL_STATES:
                return {"error": f"Cannot connect call. Call status is '{session.status}'."}, 409

            if session.status in [VoiceSession.VoiceSessionStatus.ACCEPTED, VoiceSession.VoiceSessionStatus.RINGING]:
                session.status = VoiceSession.VoiceSessionStatus.ONGOING
                session.save(update_fields=['status'])
                logger.info(f"[CALL] call_id={session.session_key} event=CALL_CONNECTED user_id={user.id}")

        return {'status': session.status, 'session_key': session.session_key}, 200

    @classmethod
    def decline_call(cls, consultation: Consultation, user, broadcast_ws=True) -> tuple[dict, int]:
        """
        Declines an incoming call attempt. Idempotent.
        """
        with transaction.atomic():
            cls.verify_and_resolve_participants(consultation, user)
            session = cls.get_voice_session(consultation, select_for_update=True)
            if not session:
                return {"error": "No voice session found."}, 404

            if session.status == VoiceSession.VoiceSessionStatus.DECLINED:
                logger.info(f"[CALL] call_id={session.session_key} event=IDEMPOTENT_DECLINE_REPEAT")
                return {'status': 'DECLINED', 'ended_at': session.ended_at}, 200

            if session.status not in [VoiceSession.VoiceSessionStatus.RINGING, VoiceSession.VoiceSessionStatus.INITIATED]:
                return {"error": f"Cannot decline call. Call status is '{session.status}'."}, 409

            old_status = session.status
            session.status = VoiceSession.VoiceSessionStatus.DECLINED
            session.ended_at = timezone.now()
            session.save()
            logger.info(f"[CALL-ACTION] action=DECLINE event=STATE_TRANSITION call_id={session.session_key} from={old_status} to={session.status} user_id={user.id}")
            logger.info(f"[CALL] call_id={session.session_key} event=CALL_DECLINED user_id={user.id}")

            if broadcast_ws:
                cls.broadcast_call_status(consultation, session, user, 'DECLINED', ended_at=session.ended_at)

        return {'status': 'DECLINED', 'ended_at': session.ended_at, 'session_key': session.session_key}, 200

    @classmethod
    def cancel_call(cls, consultation: Consultation, user, broadcast_ws=True) -> tuple[dict, int]:
        """
        Cancels an outgoing call attempt (caller side). Idempotent.
        """
        with transaction.atomic():
            cls.verify_and_resolve_participants(consultation, user)
            session = cls.get_voice_session(consultation, select_for_update=True)
            if not session:
                return {"error": "No voice session found."}, 404

            if session.status == VoiceSession.VoiceSessionStatus.CANCELLED:
                logger.info(f"[CALL] call_id={session.session_key} event=IDEMPOTENT_CANCEL_REPEAT")
                return {'status': 'CANCELLED', 'ended_at': session.ended_at}, 200

            if session.status not in [VoiceSession.VoiceSessionStatus.RINGING, VoiceSession.VoiceSessionStatus.INITIATED]:
                return {"error": f"Cannot cancel call. Call status is '{session.status}'."}, 409

            old_status = session.status
            session.status = VoiceSession.VoiceSessionStatus.CANCELLED
            session.ended_at = timezone.now()
            session.save()
            logger.info(f"[CALL-ACTION] action=CANCEL event=STATE_TRANSITION call_id={session.session_key} from={old_status} to={session.status} user_id={user.id}")
            logger.info(f"[CALL] call_id={session.session_key} event=CALL_CANCELLED user_id={user.id}")

            if broadcast_ws:
                cls.broadcast_call_status(consultation, session, user, 'CANCELLED', ended_at=session.ended_at)

        return {'status': 'CANCELLED', 'ended_at': session.ended_at, 'session_key': session.session_key}, 200

    @classmethod
    def missed_call(cls, consultation: Consultation, user=None, broadcast_ws=True) -> tuple[dict, int]:
        """
        Marks call as missed. Idempotent.
        """
        with transaction.atomic():
            if user:
                cls.verify_and_resolve_participants(consultation, user)
            session = cls.get_voice_session(consultation, select_for_update=True)
            if not session:
                return {"error": "No voice session found."}, 404

            if session.status == VoiceSession.VoiceSessionStatus.MISSED:
                return {'status': 'MISSED', 'ended_at': session.ended_at}, 200

            session.status = VoiceSession.VoiceSessionStatus.MISSED
            session.ended_at = timezone.now()
            session.save()
            logger.info(f"[CALL] call_id={session.session_key} event=CALL_MISSED")

            if user and broadcast_ws:
                cls.broadcast_call_status(consultation, session, user, 'MISSED', ended_at=session.ended_at)

        return {'status': 'MISSED', 'ended_at': session.ended_at, 'session_key': session.session_key}, 200

    @classmethod
    def end_call(cls, consultation: Consultation, user, broadcast_ws=True) -> tuple[dict, int]:
        """
        Ends an active call. Idempotent.
        """
        with transaction.atomic():
            cls.verify_and_resolve_participants(consultation, user)
            session = cls.get_voice_session(consultation, select_for_update=True)
            if not session:
                return {"error": "No voice session found."}, 404

            if session.status in TERMINAL_CALL_STATES:
                logger.info(f"[CALL] call_id={session.session_key} event=IDEMPOTENT_END_REPEAT status={session.status}")
                return {'status': session.status, 'ended_at': session.ended_at}, 200

            old_status = session.status
            session.status = VoiceSession.VoiceSessionStatus.ENDED
            session.ended_at = timezone.now()
            session.save()
            logger.info(f"[CALL-ACTION] action=END event=STATE_TRANSITION call_id={session.session_key} from={old_status} to={session.status} user_id={user.id}")
            logger.info(f"[CALL] call_id={session.session_key} event=CALL_ENDED user_id={user.id}")

            if broadcast_ws:
                cls.broadcast_call_status(consultation, session, user, 'ENDED', ended_at=session.ended_at)

        return {'status': 'ENDED', 'ended_at': session.ended_at, 'session_key': session.session_key}, 200

    @classmethod
    def generate_agora_token(cls, consultation: Consultation, user) -> tuple[dict, int]:
        """
        Generates signed Agora RTC token for an active call.
        Validates participant authorization and rejects terminal calls.
        """
        cls.verify_and_resolve_participants(consultation, user)
        session = cls.get_voice_session(consultation, select_for_update=False)
        if not session:
            return {'error': 'No voice session found for this consultation.'}, 404

        cls.check_and_auto_expire_ringing_session(session)
        agora_app_id = getattr(settings, 'AGORA_APP_ID', 'cagh_agora_app_id_placeholder')

        if session.status in TERMINAL_CALL_STATES:
            logger.warning(
                f"[CALL] call_id={session.session_key} event=TOKEN_REJECTED_TERMINAL "
                f"status={session.status} — returning 410 Gone"
            )
            # Return 410 Gone so the client can distinguish "session ended" from a
            # successful token response.  An empty token with HTTP 200 would cause
            # the Flutter client to call Agora joinChannel("") which produces error 17.
            return {
                'error': f"Voice session is no longer active (status: {session.status}).",
                'status': session.status,
                'session_key': session.session_key,
                'call_id': session.session_key,
            }, 410

        if not session.agora_channel_name:
            session.agora_channel_name = f"cagh_voice_{session.session_key}"
            session.save(update_fields=['agora_channel_name'])

        token = AgoraService.generate_rtc_token(
            channel_name=session.agora_channel_name,
            uid=user.id,
            role=AgoraRole.PUBLISHER
        )

        caller = session.caller
        _, _, recipient = cls.verify_and_resolve_participants(consultation, user)
        caller_name = cls.get_display_name(caller) or getattr(caller, 'username', 'Caller')
        recipient_name = cls.get_display_name(recipient) or getattr(recipient, 'username', 'Recipient')

        logger.info(f"[CALL] call_id={session.session_key} event=AGORA_TOKEN_GENERATED user_id={user.id}")

        return {
            'agora_app_id': agora_app_id,
            'agora_channel_name': session.agora_channel_name,
            'agora_token': token,
            'uid': AgoraService.get_numeric_uid(user.id),
            'session_key': session.session_key,
            'call_id': session.session_key,
            'status': session.status,
            'started_at': session.started_at,
            'caller_id': str(caller.id) if caller else "",
            'caller_name': caller_name,
            'receiver_id': str(recipient.id) if recipient else "",
            'recipient_id': str(recipient.id) if recipient else "",
            'receiver_name': recipient_name,
            'recipient_name': recipient_name,
            'consultation_id': str(consultation.id),
        }, 200
