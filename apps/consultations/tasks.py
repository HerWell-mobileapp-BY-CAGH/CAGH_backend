import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="apps.consultations.tasks.check_and_expire_ringing_session_task")
def check_and_expire_ringing_session_task(session_id):
    """
    Celery background task triggered when a call starts.
    Executes after countdown (e.g. 46s) to auto-expire ringing calls if still unhandled.
    """
    try:
        from .models import VoiceSession
        from .services import VoiceCallService

        session = VoiceSession.objects.filter(id=session_id).first()
        if not session:
            return

        if session.status == VoiceSession.VoiceSessionStatus.RINGING:
            session.status = VoiceSession.VoiceSessionStatus.MISSED
            session.ended_at = timezone.now()
            session.save(update_fields=['status', 'ended_at'])
            logger.info(f"[CALL] call_id={session.session_key} event=CELERY_RINGING_TIMEOUT_EXPIRED")

            if session.consultation:
                VoiceCallService.broadcast_call_status(
                    session.consultation,
                    session,
                    session.caller or session.consultation.user,
                    'MISSED',
                    ended_at=session.ended_at
                )
    except Exception as e:
        logger.error(f"[CALL] event=CELERY_RINGING_TIMEOUT_TASK_ERROR session_id={session_id} error={e}")
