import os
import json
import logging
from django.conf import settings
from .models import Notification, DeviceToken

logger = logging.getLogger(__name__)

# Robust Firebase Admin SDK Initialization
_firebase_initialized = False

def init_firebase_admin():
    global _firebase_initialized
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging

        if firebase_admin._apps and '[DEFAULT]' in firebase_admin._apps:
            app = firebase_admin.get_app()
            if getattr(app, 'project_id', None):
                _firebase_initialized = True
                return app
            try:
                firebase_admin.delete_app(app)
            except Exception:
                pass

        backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidate_paths = [
            os.path.join(backend_root, 'firebase-service-account.json'),
            os.path.join(backend_root, 'service-account.json'),
            os.path.join(backend_root, 'config', 'firebase-service-account.json'),
            r'C:\Users\hp\Desktop\CAGH_backend\firebase-service-account.json',
        ]

        cred_path = getattr(settings, 'FIREBASE_SERVICE_ACCOUNT_KEY', None) or os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY', '')
        if cred_path and cred_path.strip().startswith('{'):
            try:
                data = json.loads(cred_path)
                pid = data.get('project_id', 'cagh-bd916')
                cred = credentials.Certificate(data)
                app = firebase_admin.initialize_app(cred, options={'projectId': pid})
                _firebase_initialized = True
                logger.info(f"[FIREBASE ADMIN] Initialized from FIREBASE_SERVICE_ACCOUNT_KEY JSON string (project_id={pid}).")
                return app
            except Exception as je:
                logger.warning(f"[FIREBASE ADMIN] Failed parsing JSON string creds: {je}")
        elif cred_path and os.path.exists(cred_path):
            try:
                cred = credentials.Certificate(cred_path)
                pid = 'cagh-bd916'
                try:
                    with open(cred_path, 'r', encoding='utf-8') as f:
                        pid = json.load(f).get('project_id', pid)
                except Exception:
                    pass
                app = firebase_admin.initialize_app(cred, options={'projectId': pid})
                _firebase_initialized = True
                logger.info(f"[FIREBASE ADMIN] Initialized with key file {cred_path} (project_id={pid}).")
                return app
            except Exception as fe:
                logger.warning(f"[FIREBASE ADMIN] Failed loading key file {cred_path}: {fe}")

        for p in candidate_paths:
            if os.path.exists(p):
                try:
                    pid = 'cagh-bd916'
                    try:
                        with open(p, 'r', encoding='utf-8') as f:
                            pid = json.load(f).get('project_id', pid)
                    except Exception:
                        pass
                    cred = credentials.Certificate(p)
                    app = firebase_admin.initialize_app(cred, options={'projectId': pid})
                    _firebase_initialized = True
                    logger.info(f"[FIREBASE ADMIN] Initialized with candidate key file: {p} (project_id={pid})")
                    return app
                except Exception as pe:
                    logger.warning(f"[FIREBASE ADMIN] Error loading {p}: {pe}")

        pid = os.getenv('GOOGLE_CLOUD_PROJECT', 'cagh-bd916')
        app = firebase_admin.initialize_app(options={'projectId': pid})
        _firebase_initialized = True
        logger.info(f"[FIREBASE ADMIN] Initialized with default options (project_id={pid})")
        return app
    except Exception as e:
        logger.warning(f"[FIREBASE ADMIN] Initialization exception: {e}")
        return None

init_firebase_admin()
def send_call_offer_push(caller, recipient, consultation, call_type="VOICE", session_key=None, agora_channel_name=None, agora_app_id=None):
    """
    Sends a DATA-ONLY high-priority FCM call offer push notification to ring the recipient device.
    Strictly data-only (no 'notification' payload block) with android.priority='high' and APNS content_available=True.
    This guarantees background/killed app state handlers (e.g. FirebaseMessaging.onBackgroundMessage / CallKit)
    can intercept the raw payload and launch full-screen ringing UI.
    """
    if not recipient or (hasattr(recipient, 'id') and recipient.id == caller.id):
        logger.info(f"[CALL OFFER PUSH SKIPPED] Recipient missing or caller==recipient.")
        return None

    caller_name = getattr(caller, 'get_full_name', lambda: '')() or getattr(caller, 'username', '') or "Healthcare Provider"
    channel_name = agora_channel_name or (f"cagh_{call_type.lower()}_{session_key}" if session_key else f"cagh_consultation_{consultation.id}")
    app_id = agora_app_id or getattr(settings, 'AGORA_APP_ID', '')

    recipient_name = getattr(recipient, 'get_full_name', lambda: '')() or getattr(recipient, 'username', '') or ""
    import time
    call_payload = {
        "type": "incoming_call",
        "action": "INCOMING_CALL",
        "consultation_id": str(consultation.id),
        "call_id": session_key or str(consultation.id),
        "session_id": session_key or "",
        "session_key": session_key or "",
        "call_type": str(call_type),
        "channel_name": channel_name,
        "agora_channel_name": channel_name,
        "agora_app_id": str(app_id),
        "caller_id": str(caller.id),
        "caller_name": caller_name,
        "caller_role": str(getattr(caller, 'role', 'PATIENT')),
        "receiver_id": str(recipient.id),
        "recipient_id": str(recipient.id),
        "receiver_name": recipient_name,
        "recipient_name": recipient_name,
        "timestamp": str(int(time.time())),
    }

    tokens = list(
        DeviceToken.objects.filter(user=recipient, is_active=True).values_list('token', flat=True)
    )

    if not tokens:
        logger.info(f"[CALL OFFER PUSH] No active FCM device token registered for {recipient.username}.")
        return None

    logger.info(f"[CALL OFFER PUSH] Dispatching DATA-ONLY high-priority FCM offer to {recipient.username} ({len(tokens)} tokens). Payload: {call_payload}")

    if _firebase_initialized:
        try:
            from firebase_admin import messaging
            str_payload = {k: str(v) for k, v in call_payload.items()}
            message = messaging.MulticastMessage(
                tokens=tokens,
                data=str_payload,  # DATA-ONLY: No notification= block!
                android=messaging.AndroidConfig(
                    priority='high',
                    ttl=30,
                ),
                apns=messaging.APNSConfig(
                    headers={
                        'apns-priority': '10',
                        'apns-push-type': 'background',
                    },
                    payload=messaging.APNSPayload(
                        aps=messaging.Aps(
                            content_available=True,
                        ),
                    ),
                ),
            )
            if hasattr(messaging, 'send_each_for_multicast'):
                response = messaging.send_each_for_multicast(message)
            else:
                response = messaging.send_multicast(message)
            logger.info(f"[CALL OFFER PUSH SUCCESS] Sent to {recipient.username}. Success: {response.success_count}, Failure: {response.failure_count}")

            if response.failure_count > 0:
                for idx, resp in enumerate(response.responses):
                    if not resp.success and resp.exception:
                        err_code = str(resp.exception)
                        if 'Unregistered' in err_code or 'InvalidArgument' in err_code:
                            stale_token = tokens[idx]
                            DeviceToken.objects.filter(token=stale_token).update(is_active=False)
                            logger.info(f"[FCM TOKEN DEACTIVATED] Stale token deactivated: {stale_token[:15]}...")

            return response
        except Exception as fe:
            logger.error(f"[CALL OFFER PUSH ERROR] Failed sending data-only FCM push via Firebase Admin: {fe}")
            return None

    return None


def send_incoming_call_notification(caller, recipient, consultation, call_type="VOICE", session_key=None, agora_channel_name=None, agora_app_id=None):
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

    # 2. Trigger DATA-ONLY FCM Call Offer Push
    send_call_offer_push(
        caller=caller,
        recipient=recipient,
        consultation=consultation,
        call_type=call_type,
        session_key=session_key,
        agora_channel_name=agora_channel_name,
        agora_app_id=agora_app_id,
    )

    return notification
