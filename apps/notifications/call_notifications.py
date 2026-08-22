import os
import logging
from django.conf import settings
from .models import Notification, DeviceToken

logger = logging.getLogger(__name__)

# Firebase Admin SDK Initialization
_firebase_initialized = False
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    
    if not firebase_admin._apps:
        cred_path = getattr(settings, 'FIREBASE_SERVICE_ACCOUNT_KEY', None) or os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY', '')
        if cred_path and os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
            _firebase_initialized = True
            logger.info(f"[FIREBASE ADMIN] Initialized with key file: {cred_path}")
        else:
            # Check for service-account.json in backend root or config folder
            backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            candidate_paths = [
                os.path.join(backend_root, 'firebase-service-account.json'),
                os.path.join(backend_root, 'service-account.json'),
                os.path.join(backend_root, 'config', 'firebase-service-account.json'),
            ]
            found = False
            for p in candidate_paths:
                if os.path.exists(p):
                    cred = credentials.Certificate(p)
                    firebase_admin.initialize_app(cred)
                    _firebase_initialized = True
                    found = True
                    logger.info(f"[FIREBASE ADMIN] Initialized with candidate key file: {p}")
                    break
            if not found:
                try:
                    firebase_admin.initialize_app()
                    _firebase_initialized = True
                    logger.info("[FIREBASE ADMIN] Initialized with default application credentials.")
                except Exception as fe:
                    logger.warning(f"[FIREBASE ADMIN] Key file not found yet. Place firebase-service-account.json in CAGH_backend root directory.")
    else:
        _firebase_initialized = True
except Exception as e:
    logger.warning(f"[FIREBASE ADMIN] Initialization notice: {e}")


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

    # 3. Dispatch FCM push notification via Firebase Admin SDK
    if tokens:
        logger.info(f"[FCM CALL PUSH] Dispatched incoming {call_type} call ringing alert to user {recipient.username} ({len(tokens)} device tokens). Payload: {call_payload}")
        if _firebase_initialized:
            try:
                from firebase_admin import messaging
                str_payload = {k: str(v) for k, v in call_payload.items()}
                message = messaging.MulticastMessage(
                    tokens=tokens,
                    data=str_payload,
                    android=messaging.AndroidConfig(
                        priority='high',
                        ttl=30,
                        notification=messaging.AndroidNotification(
                            title=title,
                            body=body,
                            sound='default',
                            channel_id='incoming_calls',
                        ),
                    ),
                    apns=messaging.APNSConfig(
                        payload=messaging.APNSPayload(
                            aps=messaging.Aps(
                                sound='default',
                                content_available=True,
                            ),
                        ),
                    ),
                )
                response = messaging.send_multicast(message)
                logger.info(f"[FCM CALL PUSH SUCCESS] Sent to {recipient.username}. Success: {response.success_count}, Failure: {response.failure_count}")
            except Exception as fe:
                logger.error(f"[FCM CALL PUSH ERROR] Failed sending FCM push via Firebase Admin: {fe}")
    else:
        logger.info(f"[IN-APP CALL NOTIFICATION] Dispatched call alert for user {recipient.username} (No active FCM token registered yet). Payload: {call_payload}")

    return notification
