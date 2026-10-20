import uuid
import logging
from datetime import timedelta
from django.db import transaction
from django.utils import timezone
from django.conf import settings
from rest_framework.exceptions import PermissionDenied, ValidationError
from .models import Consultation, VoiceSession

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
        Auto-expires a ringing call if no response within RINGING_TIMEOUT_SECONDS (45s).
        Also auto-expires an ACCEPTED session if media never connected within stale threshold (60s).
        """
        if not session:
            return

        reference_time = getattr(session, 'updated_at', None) or session.started_at or (session.consultation.updated_at if session.consultation else None)
        if session.status == VoiceSession.VoiceSessionStatus.RINGING:
            if reference_time and (timezone.now() - reference_time) > timedelta(seconds=RINGING_TIMEOUT_SECONDS):
                session.status = VoiceSession.VoiceSessionStatus.MISSED
                session.ended_at = timezone.now()
                session.save(update_fields=['status', 'ended_at'])
                logger.info(f"[CALL] call_id={session.session_key} event=AUTO_EXPIRED_RINGING_TIMEOUT")
        elif session.status == VoiceSession.VoiceSessionStatus.ACCEPTED:
            stale_threshold = getattr(settings, 'VOICE_CALL_STALE_ACCEPTED_TIMEOUT_SECONDS', 60)
            if reference_time and (timezone.now() - reference_time) > timedelta(seconds=stale_threshold):
                session.status = VoiceSession.VoiceSessionStatus.FAILED
                session.ended_at = timezone.now()
                session.save(update_fields=['status', 'ended_at'])
                logger.info(f"[CALL] call_id={session.session_key} event=AUTO_EXPIRED_STALE_ACCEPTED_TIMEOUT")

    @classmethod
    def broadcast_call_status(cls, consultation: Consultation, session: VoiceSession, user, action_type: str, ended_at=None):
        """
        Legacy signaling hook retained as a safe no-op now that in-app voice
        signaling has been replaced by SIM-based phone calls.
        """
        pass

    @classmethod
    def get_voice_session(cls, consultation: Consultation, select_for_update=False) -> VoiceSession:
        qs = VoiceSession.objects.filter(consultation=consultation)
        if select_for_update:
            qs = qs.select_for_update()

        active = qs.exclude(status__in=TERMINAL_CALL_STATES).order_by('-created_at').first()
        if active:
            cls.check_and_auto_expire_ringing_session(active)
            if active.status not in TERMINAL_CALL_STATES:
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
                is_new_call_attempt = False
                logger.info(f"[CALL] call_id={session_key} event=REUSING_ACTIVE_SESSION status={session.status}")
            else:
                session_key = f"VOICE-{uuid.uuid4().hex[:12].upper()}"
                session = VoiceSession.objects.create(
                    consultation=consultation,
                    session_key=session_key,
                    status=VoiceSession.VoiceSessionStatus.RINGING,
                    caller=caller,
                )
                is_new_call_attempt = True
                logger.info(f"[CALL] call_id={session_key} event=VOICE_SESSION_CREATED caller={caller.id} receiver={getattr(recipient, 'id', None)}")

        caller_name = cls.get_display_name(caller) or getattr(caller, 'username', 'Caller')
        recipient_name = cls.get_display_name(recipient) or getattr(recipient, 'username', 'Recipient')

        # Schedule Celery background ringing timeout execution
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

        return {
            'status': session.status,
            'started_at': session.started_at,
            'call_type': call_type,
            'session_key': session_key,
            'call_id': session_key,
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
                session.save()
                consultation.status = Consultation.ConsultationStatus.ACTIVE
                if not consultation.started_at:
                    consultation.started_at = timezone.now()
                consultation.save()

                logger.info(f"[CALL-ACTION] action=ACCEPT event=STATE_TRANSITION call_id={session.session_key} from={old_status} to={session.status} user_id={user.id}")
                logger.info(f"[CALL] call_id={session.session_key} event=CALL_ACCEPTED user_id={user.id}")

        if broadcast_ws and not is_idempotent_repeat:
            cls.broadcast_call_status(consultation, session, user, 'ACCEPTED')

        caller = session.caller
        _, _, recipient = cls.verify_and_resolve_participants(consultation, user)
        caller_name = cls.get_display_name(caller) or getattr(caller, 'username', 'Caller')
        recipient_name = cls.get_display_name(recipient) or getattr(recipient, 'username', 'Recipient')

        return {
            'status': session.status,
            'session_key': session.session_key,
            'call_id': session.session_key,
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
        Marks call ONGOING/ACTIVE when voice session connects.
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


