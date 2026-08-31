import os
import json
import base64
import logging
import time
from django.conf import settings
from .models import Notification, DeviceToken

logger = logging.getLogger(__name__)

# Robust Firebase Admin SDK Initialization
_firebase_initialized = False


def normalize_firebase_credentials(data):
    """
    Normalizes Firebase credentials dictionary.
    Replaces literal escaped '\\n' strings in private_key with actual newline characters.
    """
    if isinstance(data, dict):
        data_copy = dict(data)
        if 'private_key' in data_copy and isinstance(data_copy['private_key'], str):
            data_copy['private_key'] = data_copy['private_key'].replace('\\n', '\n')
        return data_copy
    return data


def init_firebase_admin():
    """
    Initializes Firebase Admin SDK using service account credentials.
    Supports:
    1. FIREBASE_SERVICE_ACCOUNT_KEY env var / Django setting as raw JSON string.
    2. FIREBASE_SERVICE_ACCOUNT_KEY as Base64-encoded JSON string.
    3. GOOGLE_APPLICATION_CREDENTIALS or file path to JSON credential file.
    4. Local candidate service-account JSON file paths.

    Explicitly DOES NOT fall back silently to Application Default Credentials (ADC)
    unless explicitly enabled via FIREBASE_USE_ADC environment variable, preventing
    runtime OAuth failure errors on non-GCP environments like Render.
    """
    global _firebase_initialized
    logger.info("[FIREBASE] initialization_started")
    try:
        import firebase_admin
        from firebase_admin import credentials, messaging

        if firebase_admin._apps and '[DEFAULT]' in firebase_admin._apps:
            app = firebase_admin.get_app()
            pid = getattr(app, 'project_id', None) or 'cagh-bd916'
            _firebase_initialized = True
            logger.info("[FIREBASE] credentials_present=true")
            logger.info(f"[FIREBASE] initialization_success project_id={pid}")
            return app

        env_raw = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY') or os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON') or getattr(settings, 'FIREBASE_SERVICE_ACCOUNT_KEY', None)
        credentials_present = bool(env_raw or os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))
        logger.info(f"[FIREBASE] credentials_present={str(credentials_present).lower()}")

        # 1. Direct JSON string or Base64 encoded JSON string
        if env_raw:
            env_str = str(env_raw).strip()
            # Try raw JSON
            if env_str.startswith('{'):
                try:
                    data = normalize_firebase_credentials(json.loads(env_str))
                    pid = data.get('project_id', 'cagh-bd916')
                    cred = credentials.Certificate(data)
                    app = firebase_admin.initialize_app(cred, options={'projectId': pid})
                    _firebase_initialized = True
                    logger.info(f"[FIREBASE] initialization_success project_id={pid}")
                    return app
                except Exception as je:
                    logger.warning(f"[FIREBASE ADMIN] Failed parsing raw JSON env var: {je}")

            # Try Base64 encoded JSON
            try:
                decoded_bytes = base64.b64decode(env_str)
                decoded_str = decoded_bytes.decode('utf-8').strip()
                if decoded_str.startswith('{'):
                    data = normalize_firebase_credentials(json.loads(decoded_str))
                    pid = data.get('project_id', 'cagh-bd916')
                    cred = credentials.Certificate(data)
                    app = firebase_admin.initialize_app(cred, options={'projectId': pid})
                    _firebase_initialized = True
                    logger.info(f"[FIREBASE] initialization_success project_id={pid}")
                    return app
            except Exception:
                pass

        # 2. File path from GOOGLE_APPLICATION_CREDENTIALS or FIREBASE_SERVICE_ACCOUNT_KEY
        gac_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        if not gac_path and env_raw:
            candidate_path = str(env_raw).strip()
            try:
                if os.path.exists(candidate_path):
                    gac_path = candidate_path
            except Exception:
                pass

        if gac_path and os.path.exists(gac_path):
            try:
                pid = 'cagh-bd916'
                try:
                    with open(gac_path, 'r', encoding='utf-8') as f:
                        file_data = normalize_firebase_credentials(json.load(f))
                        pid = file_data.get('project_id', pid)
                        cred = credentials.Certificate(file_data)
                except Exception:
                    cred = credentials.Certificate(gac_path)
                app = firebase_admin.initialize_app(cred, options={'projectId': pid})
                _firebase_initialized = True
                logger.info(f"[FIREBASE] initialization_success project_id={pid}")
                return app
            except Exception as fe:
                logger.warning(f"[FIREBASE ADMIN] Failed loading key file {gac_path}: {fe}")

        # 3. Local candidate key file paths
        backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        candidate_paths = [
            os.path.join(backend_root, 'firebase-service-account.json'),
            os.path.join(backend_root, 'service-account.json'),
            os.path.join(backend_root, 'config', 'firebase-service-account.json'),
        ]

        for p in candidate_paths:
            try:
                if os.path.exists(p):
                    pid = 'cagh-bd916'
                    try:
                        with open(p, 'r', encoding='utf-8') as f:
                            file_data = normalize_firebase_credentials(json.load(f))
                            pid = file_data.get('project_id', pid)
                            cred = credentials.Certificate(file_data)
                    except Exception:
                        cred = credentials.Certificate(p)
                    app = firebase_admin.initialize_app(cred, options={'projectId': pid})
                    _firebase_initialized = True
                    logger.info(f"[FIREBASE] initialization_success project_id={pid}")
                    return app
            except Exception as pe:
                logger.warning(f"[FIREBASE ADMIN] Error loading candidate key file {p}: {pe}")

        # 4. ADC (Only if explicitly enabled via FIREBASE_USE_ADC env var)
        if os.getenv('FIREBASE_USE_ADC', '').lower() == 'true':
            try:
                cred = credentials.ApplicationDefault()
                pid = os.getenv('FIREBASE_PROJECT_ID') or os.getenv('GOOGLE_CLOUD_PROJECT') or 'cagh-bd916'
                app = firebase_admin.initialize_app(cred, options={'projectId': pid})
                _firebase_initialized = True
                logger.info(f"[FIREBASE] initialization_success project_id={pid}")
                return app
            except Exception as adce:
                logger.warning(f"[FIREBASE ADMIN] ADC initialization failed: {adce}")

        _firebase_initialized = False
        logger.error("[FIREBASE] initialization_failed error=credentials_unavailable")
        return None
    except Exception as e:
        _firebase_initialized = False
        logger.error(f"[FIREBASE] initialization_failed error={e}")
        return None


init_firebase_admin()


def send_call_offer_push(caller, recipient, consultation, call_type="VOICE", session_key=None, agora_channel_name=None, agora_app_id=None):
    """
    Sends a DATA-ONLY high-priority FCM call offer push notification to ring the recipient device.
    Strictly data-only (no 'notification' payload block) with android.priority='high' and APNS content_available=True.
    Guarantees background/killed app state handlers can launch full-screen incoming call UI.
    Does NOT corrupt call state if Firebase is unavailable or fails.
    """
    caller_id = str(getattr(caller, 'id', ''))
    recipient_id = str(getattr(recipient, 'id', ''))

    if not recipient or not recipient_id or caller_id == recipient_id:
        logger.info(f"[CALL] call_id={session_key} event=FCM_SKIPPED reason=recipient_missing_or_self caller_id={caller_id} receiver_id={recipient_id}")
        return None

    fb_app = init_firebase_admin()
    if not fb_app:
        logger.warning(f"[CALL] call_id={session_key} event=FCM_SKIPPED reason=firebase_not_initialized receiver={recipient_id}")
        return None

    caller_name = getattr(caller, 'get_full_name', lambda: '')() or getattr(caller, 'username', '') or "Healthcare Provider"
    recipient_name = getattr(recipient, 'get_full_name', lambda: '')() or getattr(recipient, 'username', '') or "Recipient"
    channel_name = agora_channel_name or (f"cagh_{call_type.lower()}_{session_key}" if session_key else f"cagh_consultation_{consultation.id}")
    app_id = agora_app_id or getattr(settings, 'AGORA_APP_ID', '')

    call_payload = {
        "type": "incoming_call",
        "action": "INCOMING_CALL",
        "consultation_id": str(consultation.id),
        "call_id": session_key or str(consultation.id),
        "session_id": session_key or str(consultation.id),
        "session_key": session_key or str(consultation.id),
        "call_type": str(call_type),
        "channel_name": str(channel_name),
        "agora_channel_name": str(channel_name),
        "agora_app_id": str(app_id),
        "caller_id": caller_id,
        "caller_name": caller_name,
        "caller_role": str(getattr(caller, 'role', 'PATIENT')),
        "receiver_id": recipient_id,
        "recipient_id": recipient_id,
        "receiver_name": recipient_name,
        "recipient_name": recipient_name,
        "timestamp": str(int(time.time())),
    }

    raw_tokens = list(
        DeviceToken.objects.filter(user=recipient, is_active=True).values_list('token', flat=True)
    )
    tokens = list(dict.fromkeys([t.strip() for t in raw_tokens if t and t.strip()]))

    if not tokens:
        logger.info(f"[CALL] call_id={session_key} event=FCM_NO_TOKENS receiver={recipient_id}")
        return None

    logger.info(f"[CALL] call_id={session_key} event=FCM_DISPATCHING caller={caller_id} receiver={recipient_id} token_count={len(tokens)}")

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
            response = messaging.send_each_for_multicast(message, app=fb_app)
        else:
            response = messaging.send_multicast(message, app=fb_app)

        if response.failure_count > 0:
            logger.info(f"[CALL] call_id={session_key} event=FCM_PARTIAL_FAILURE receiver={recipient_id} success_count={response.success_count} failure_count={response.failure_count}")
            for idx, resp in enumerate(response.responses):
                if not resp.success and resp.exception:
                    err_code = str(resp.exception)
                    if 'Unregistered' in err_code or 'InvalidArgument' in err_code:
                        stale_token = tokens[idx]
                        DeviceToken.objects.filter(token=stale_token).update(is_active=False)
                        logger.info(f"[CALL] call_id={session_key} event=FCM_TOKEN_DEACTIVATED receiver={recipient_id}")
        else:
            logger.info(f"[CALL] call_id={session_key} event=FCM_SENT receiver={recipient_id} success_count={response.success_count} failure_count={response.failure_count}")

        return response
    except Exception as fe:
        logger.error(f"[CALL] call_id={session_key} event=FCM_SEND_FAILED receiver={recipient_id} error={fe}")
        return None


def send_incoming_call_notification(caller, recipient, consultation, call_type="VOICE", session_key=None, agora_channel_name=None, agora_app_id=None):
    """
    Triggers an in-app Notification record and high-priority FCM call offer push notification.
    Strictly prevents self-calling (caller == recipient).
    """
    caller_id = str(getattr(caller, 'id', ''))
    recipient_id = str(getattr(recipient, 'id', ''))

    if not recipient or not recipient_id or caller_id == recipient_id:
        logger.info(f"[CALL] call_id={session_key} event=CALL_NOTIFICATION_SKIPPED reason=self_call_or_missing_recipient caller_id={caller_id}")
        return None

    caller_name = getattr(caller, 'get_full_name', lambda: '')() or getattr(caller, 'username', '') or "Healthcare Provider"

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

