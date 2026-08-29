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
            os.path.join(r'C:\Users\hp\Desktop\CAGH_backend', 'firebase-service-account.json'),
        ]

        # 1. Environment variable containing JSON string
        env_raw = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY') or os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON') or getattr(settings, 'FIREBASE_SERVICE_ACCOUNT_KEY', None)
        if env_raw and str(env_raw).strip().startswith('{'):
            try:
                data = json.loads(env_raw)
                pid = data.get('project_id', 'cagh-bd916')
                cred = credentials.Certificate(data)
                app = firebase_admin.initialize_app(cred, options={'projectId': pid})
                _firebase_initialized = True
                logger.info(f'[FIREBASE ADMIN] Firebase Admin initialized successfully from JSON env var (project_id={pid}).')
                return app
            except Exception as je:
                logger.warning(f'[FIREBASE ADMIN] Failed parsing JSON env var creds: {je}')

        # 2. GOOGLE_APPLICATION_CREDENTIALS or file path
        gac_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS') or (env_raw if env_raw and os.path.exists(str(env_raw)) else None)
        if gac_path and os.path.exists(gac_path):
            try:
                cred = credentials.Certificate(gac_path)
                pid = 'cagh-bd916'
                try:
                    with open(gac_path, 'r', encoding='utf-8') as f:
                        pid = json.load(f).get('project_id', pid)
                except Exception:
                    pass
                app = firebase_admin.initialize_app(cred, options={'projectId': pid})
                _firebase_initialized = True
                logger.info(f'[FIREBASE ADMIN] Firebase Admin initialized successfully with key file {gac_path} (project_id={pid}).')
                return app
            except Exception as fe:
                logger.warning(f'[FIREBASE ADMIN] Failed loading key file {gac_path}: {fe}')

        # 3. Local candidate key file paths
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
                    logger.info(f'[FIREBASE ADMIN] Firebase Admin initialized successfully with candidate key file: {p} (project_id={pid}).')
                    return app
                except Exception as pe:
                    logger.warning(f'[FIREBASE ADMIN] Error loading candidate key file {p}: {pe}')

        # 4. Try Application Default Credentials (ADC) or default projectId (Render / GCP env)
        try:
            cred = credentials.ApplicationDefault()
            pid = os.getenv('FIREBASE_PROJECT_ID') or os.getenv('GOOGLE_CLOUD_PROJECT') or 'cagh-bd916'
            app = firebase_admin.initialize_app(cred, options={'projectId': pid})
            _firebase_initialized = True
            logger.info(f'[FIREBASE ADMIN] Firebase Admin initialized with Application Default Credentials (project_id={pid}).')
            return app
        except Exception as adce:
            logger.debug(f'[FIREBASE ADMIN] ADC initialization attempt skipped: {adce}')

        _firebase_initialized = False
        logger.error('[FIREBASE ADMIN ERROR] Firebase Admin credentials unavailable. FCM pushes cannot be dispatched. Please set FIREBASE_SERVICE_ACCOUNT_KEY or GOOGLE_APPLICATION_CREDENTIALS.')
        return None
    except Exception as e:
        _firebase_initialized = False
        logger.error(f'[FIREBASE ADMIN ERROR] Initialization exception: {e}')
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
            fb_app = init_firebase_admin()
            if hasattr(messaging, 'send_each_for_multicast'):
                response = messaging.send_each_for_multicast(message, app=fb_app) if fb_app else messaging.send_each_for_multicast(message)
            else:
                response = messaging.send_multicast(message, app=fb_app) if fb_app else messaging.send_multicast(message)
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
