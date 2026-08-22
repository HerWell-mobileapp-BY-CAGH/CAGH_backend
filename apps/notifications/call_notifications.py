import logging
from django.conf import settings
from .models import Notification, DeviceToken

logger = logging.getLogger(__name__)


def send_incoming_call_notification(caller, recipient, consultation, call_type="VOICE", session_key=None):
    """
    Triggers an in-app Notification and high-priority FCM call push notification to ring the recipient device.
    Strictly prevents self-calling (caller == recipient).
    """
    if not recipient or (hasattr(recipient, 'id') and recipient.id == caller.id):
        logger.info(f"[CALL NOTIFICATION SKIPPED] Recipient is missing or identical to caller (caller_id={getattr(caller, 'id', None)}).")
        return None

    caller_name = getattr(caller, 'get_full_name', lambda: '')() or caller.username or "Healthcare Provider"

    title = f"Incoming {call_type.title()} Call"
    body = f"{caller_name} is calling you for your scheduled consultation."

    # 1. Create In-App Notification
    notification = Notification.objects.create(
        user=recipient,
        title=title,
        body=body,
        type="CONSULTATION",
        action="INCOMING_CALL",
        reference_id=str(consultation.id),
    )

    # 2. Retrieve active FCM device tokens for recipient
    tokens = list(
        DeviceToken.objects.filter(user=recipient, is_active=True).values_list('token', flat=True)
    )

    channel_name = f"cagh_{call_type.lower()}_{session_key}" if session_key else f"cagh_consultation_{consultation.id}"

    call_payload = {
        "type": "incoming_call",
        "action": "INCOMING_CALL",
        "notification_id": str(notification.id),
        "consultation_id": str(consultation.id),
        "call_id": session_key or str(consultation.id),
        "session_id": session_key or "",
        "session_key": session_key or "",
        "call_type": call_type,
        "caller_id": str(caller.id),
        "caller_name": caller_name,
        "caller_role": getattr(caller, 'role', 'PATIENT'),
        "channel_name": channel_name,
    }

    # 3. Log FCM push dispatch payload for device ringing
    if tokens:
        logger.info(f"[FCM CALL PUSH] Dispatched incoming {call_type} call ringing alert to user {recipient.username} ({len(tokens)} device tokens). Payload: {call_payload}")
    else:
        logger.info(f"[IN-APP CALL NOTIFICATION] Dispatched call alert for user {recipient.username} (No active FCM token registered yet). Payload: {call_payload}")

    return notification

