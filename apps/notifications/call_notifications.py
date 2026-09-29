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


def validate_firebase_credentials(data):
    """
    Validates mandatory Firebase service account JSON schema fields.
    Normalizes escaped '\\n' in private_key into actual newline characters.
    Returns (is_valid, reason, normalized_data)
    """
    if not isinstance(data, dict):
        return False, "invalid_json_type", None

    data_copy = dict(data)
    if 'token_uri' not in data_copy or not data_copy['token_uri']:
        data_copy['token_uri'] = "https://oauth2.googleapis.com/token"

    required_fields = ['type', 'project_id', 'private_key', 'client_email', 'token_uri']
    missing = [f for f in required_fields if not data_copy.get(f)]
    if missing:
        return False, f"missing_required_fields_{','.join(missing)}", None

    pk = data_copy.get('private_key', '')
    if isinstance(pk, str):
        pk = pk.replace('\\n', '\n')
        data_copy['private_key'] = pk

    if '-----BEGIN PRIVATE KEY-----' not in pk or '-----END PRIVATE KEY-----' not in pk:
        return False, "invalid_private_key_pem_format", None

    return True, "valid", data_copy


def normalize_firebase_credentials(data):
    """
    Helper function for backward compatibility credential normalization.
    """
    _, _, normalized = validate_firebase_credentials(data)
    return normalized if normalized else data


def init_firebase_admin():
    """
    Initializes Firebase Admin SDK using service account credentials.
    Supports:
    1. FIREBASE_SERVICE_ACCOUNT_KEY env var / Django setting as raw JSON, base64, or file path.
    2. FIREBASE_SERVICE_ACCOUNT_JSON env var.
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

        env_key_raw = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY')
        env_json_raw = os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON')
        gac_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')

        has_explicit_env = bool(env_key_raw or env_json_raw)
        env_key = env_key_raw or getattr(settings, 'FIREBASE_SERVICE_ACCOUNT_KEY', None)

        credentials_present = bool(env_key or env_json_raw or gac_path)
        logger.info(f"[FIREBASE] credentials_present={str(credentials_present).lower()}")

        # If no explicit env var is overriding, and existing default app is present:
        if not has_explicit_env and firebase_admin._apps and '[DEFAULT]' in firebase_admin._apps:
            app = firebase_admin.get_app()
            pid = getattr(app, 'project_id', None) or 'cagh-bd916'
            _firebase_initialized = True
            logger.info("[FIREBASE] credential_source=existing_app")
            logger.info("[FIREBASE] credential_parse_success=true")
            logger.info(f"[FIREBASE] initialization_success project_id={pid}")
            return app

        parsed_data = None
        source_name = None
        format_name = None

        # 1. Direct FIREBASE_SERVICE_ACCOUNT_KEY
        if env_key:
            env_str = str(env_key).strip()
            if env_str.startswith('{'):
                source_name = "FIREBASE_SERVICE_ACCOUNT_KEY"
                format_name = "raw_json"
                try:
                    raw_dict = json.loads(env_str)
                    is_valid, reason, parsed_data = validate_firebase_credentials(raw_dict)
                    if not is_valid:
                        logger.warning(f"[FIREBASE] credential_parse_failed source={source_name} format={format_name} reason={reason}")
                        parsed_data = None
                except Exception as je:
                    logger.warning(f"[FIREBASE] credential_parse_failed source={source_name} format={format_name} reason=invalid_json error={je}")

            if not parsed_data:
                try:
                    decoded_str = base64.b64decode(env_str).decode('utf-8').strip()
                    if decoded_str.startswith('{'):
                        source_name = "FIREBASE_SERVICE_ACCOUNT_KEY"
                        format_name = "base64_json"
                        raw_dict = json.loads(decoded_str)
                        is_valid, reason, parsed_data = validate_firebase_credentials(raw_dict)
                        if not is_valid:
                            logger.warning(f"[FIREBASE] credential_parse_failed source={source_name} format={format_name} reason={reason}")
                            parsed_data = None
                except Exception:
                    pass

            if not parsed_data and os.path.exists(env_str):
                source_name = "FIREBASE_SERVICE_ACCOUNT_KEY"
                format_name = "file_path"
                try:
                    with open(env_str, 'r', encoding='utf-8') as f:
                        raw_dict = json.load(f)
                        is_valid, reason, parsed_data = validate_firebase_credentials(raw_dict)
                        if not is_valid:
                            logger.warning(f"[FIREBASE] credential_parse_failed source={source_name} format={format_name} reason={reason}")
                            parsed_data = None
                except Exception as fe:
                    logger.warning(f"[FIREBASE] credential_parse_failed source={source_name} format={format_name} reason=file_read_error error={fe}")

        # 2. FIREBASE_SERVICE_ACCOUNT_JSON
        if not parsed_data and env_json_raw:
            env_str = str(env_json_raw).strip()
            if env_str.startswith('{'):
                source_name = "FIREBASE_SERVICE_ACCOUNT_JSON"
                format_name = "raw_json"
                try:
                    raw_dict = json.loads(env_str)
                    is_valid, reason, parsed_data = validate_firebase_credentials(raw_dict)
                    if not is_valid:
                        logger.warning(f"[FIREBASE] credential_parse_failed source={source_name} format={format_name} reason={reason}")
                        parsed_data = None
                except Exception as e:
                    logger.warning(f"[FIREBASE] credential_parse_failed source={source_name} format={format_name} reason=invalid_json error={e}")

        # If explicit environment variable was passed but could NOT be parsed into valid credentials, fail immediately
        if has_explicit_env and not parsed_data:
            _firebase_initialized = False
            logger.error("[FIREBASE] initialization_failed error=credentials_unavailable")
            return None

        # 3. GOOGLE_APPLICATION_CREDENTIALS
        if not parsed_data and gac_path and os.path.exists(gac_path):
            source_name = "GOOGLE_APPLICATION_CREDENTIALS"
            format_name = "file_path"
            try:
                with open(gac_path, 'r', encoding='utf-8') as f:
                    raw_dict = json.load(f)
                    is_valid, reason, parsed_data = validate_firebase_credentials(raw_dict)
                    if not is_valid:
                        logger.warning(f"[FIREBASE] credential_parse_failed source={source_name} format={format_name} reason={reason}")
                        parsed_data = None
            except Exception as fe:
                logger.warning(f"[FIREBASE] credential_parse_failed source={source_name} format={format_name} reason=file_read_error error={fe}")

        # 4. Local candidate key file paths
        if not parsed_data:
            backend_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            candidate_paths = [
                os.path.join(backend_root, 'firebase-service-account.json'),
                os.path.join(backend_root, 'service-account.json'),
                os.path.join(backend_root, 'config', 'firebase-service-account.json'),
            ]

            for p in candidate_paths:
                if os.path.exists(p):
                    source_name = "candidate_file"
                    format_name = "file_path"
                    try:
                        with open(p, 'r', encoding='utf-8') as f:
                            raw_dict = json.load(f)
                            is_valid, reason, parsed_data = validate_firebase_credentials(raw_dict)
                            if is_valid:
                                break
                    except Exception:
                        pass

        # 5. ADC (Only if explicitly enabled via FIREBASE_USE_ADC env var)
        if not parsed_data and os.getenv('FIREBASE_USE_ADC', '').lower() == 'true':
            try:
                cred = credentials.ApplicationDefault()
                pid = os.getenv('FIREBASE_PROJECT_ID') or os.getenv('GOOGLE_CLOUD_PROJECT') or 'cagh-bd916'
                try:
                    app = firebase_admin.initialize_app(cred, options={'projectId': pid})
                except ValueError:
                    app = firebase_admin.get_app()
                _firebase_initialized = True
                logger.info("[FIREBASE] credential_source=FIREBASE_USE_ADC")
                logger.info("[FIREBASE] credential_format=application_default")
                logger.info("[FIREBASE] credential_parse_success=true")
                logger.info(f"[FIREBASE] initialization_success project_id={pid}")
                return app
            except Exception as adce:
                logger.warning(f"[FIREBASE] ADC initialization failed: {adce}")

        if parsed_data:
            pid = parsed_data.get('project_id', 'cagh-bd916')
            cred = credentials.Certificate(parsed_data)
            try:
                app = firebase_admin.initialize_app(cred, options={'projectId': pid})
            except ValueError:
                app = firebase_admin.get_app()
            _firebase_initialized = True
            logger.info(f"[FIREBASE] credential_source={source_name}")
            logger.info(f"[FIREBASE] credential_format={format_name}")
            logger.info("[FIREBASE] credential_parse_success=true")
            logger.info(f"[FIREBASE] initialization_success project_id={pid}")
            return app

        if firebase_admin._apps and '[DEFAULT]' in firebase_admin._apps:
            app = firebase_admin.get_app()
            pid = getattr(app, 'project_id', None) or 'cagh-bd916'
            _firebase_initialized = True
            logger.info("[FIREBASE] credential_source=existing_app")
            logger.info("[FIREBASE] credential_parse_success=true")
            logger.info(f"[FIREBASE] initialization_success project_id={pid}")
            return app

        _firebase_initialized = False
        logger.info("[FIREBASE] initialization_skipped reason=credentials_unavailable")
        return None
    except Exception as e:
        _firebase_initialized = False
        logger.error(f"[FIREBASE] initialization_failed error={e}")
        return None


init_firebase_admin()


def _get_initialized_firebase_app():
    """Return the Firebase app after initialization, reusing the default app."""
    if not _firebase_initialized:
        configured_credentials = any(
            os.getenv(name) or getattr(settings, name, None)
            for name in (
                'FIREBASE_SERVICE_ACCOUNT_KEY',
                'FIREBASE_SERVICE_ACCOUNT_JSON',
                'GOOGLE_APPLICATION_CREDENTIALS',
            )
        )
        if not configured_credentials and os.getenv('FIREBASE_USE_ADC', '').lower() != 'true':
            return None
        return init_firebase_admin()

    try:
        import firebase_admin
        return firebase_admin.get_app()
    except (ImportError, ValueError):
        # FCM calls can still be mocked in tests where initialization is mocked.
        return None


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

    fb_app = _get_initialized_firebase_app()
    if not _firebase_initialized:
        logger.info(f"[CALL] call_id={session_key} event=FCM_SKIPPED reason=firebase_not_initialized receiver={recipient_id}")
        return None

    caller_name = getattr(caller, 'get_full_name', lambda: '')() or getattr(caller, 'username', '') or "Healthcare Provider"
    recipient_name = getattr(recipient, 'get_full_name', lambda: '')() or getattr(recipient, 'username', '') or "Recipient"
    call_id_str = session_key or str(consultation.id)

    call_payload = {
        "type": "incoming_call",
        "action": "INCOMING_CALL",
        "consultation_id": str(consultation.id),
        "call_id": call_id_str,
        "session_id": call_id_str,
        "session_key": call_id_str,
        "call_type": str(call_type),
        "caller_id": caller_id,
        "caller_name": caller_name,
        "caller_role": str(getattr(caller, 'role', 'PATIENT')),
        "receiver_id": recipient_id,
        "recipient_id": recipient_id,
        "receiver_name": recipient_name,
        "recipient_name": recipient_name,
        "timestamp": str(int(time.time())),
        "webrtc_enabled": "true",
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

        if response.failure_count > 0 and response.success_count > 0:
            logger.info(f"[CALL] call_id={session_key} event=FCM_PARTIAL_FAILURE receiver={recipient_id} success_count={response.success_count} failure_count={response.failure_count}")
        elif response.failure_count > 0 and response.success_count == 0:
            logger.error(f"[CALL] call_id={session_key} event=FCM_FAILED receiver={recipient_id} success_count=0 failure_count={response.failure_count}")
        else:
            logger.info(f"[CALL] call_id={session_key} event=FCM_SENT receiver={recipient_id} success_count={response.success_count} failure_count={response.failure_count}")

        if response.failure_count > 0:
            for idx, resp in enumerate(response.responses):
                if not resp.success:
                    exc = resp.exception
                    err_code = getattr(exc, 'code', None) or getattr(exc, 'error_code', None) or type(exc).__name__ if exc else "UNKNOWN_ERROR"
                    err_msg = str(exc) if exc else "No exception detail"

                    logger.error(
                        f"[CALL] call_id={session_key} event=FCM_TOKEN_FAILED receiver={recipient_id} "
                        f"index={idx} code={err_code} message={err_msg}"
                    )

                    err_str = f"{err_code} {err_msg}".lower()
                    if any(pattern in err_str for pattern in ['unregistered', 'invalid_argument', 'invalid-argument', 'not_found', 'not-found', 'sender_id_mismatch', 'sender-id-mismatch']):
                        stale_token = tokens[idx]
                        DeviceToken.objects.filter(token=stale_token).update(is_active=False)
                        logger.info(f"[CALL] call_id={session_key} event=FCM_TOKEN_DEACTIVATED receiver={recipient_id} index={idx} code={err_code}")

        return response
    except Exception as fe:
        logger.error(f"[CALL] call_id={session_key} event=FCM_FAILED receiver={recipient_id} error={fe}")
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


def send_general_push_notification(user, title, body, extra_data=None):
    """
    Sends a standard FCM Push Notification (title + body + data payload)
    to all active registered device tokens of a user.
    Respects user NotificationPreferences (enable_push_notifications).
    """
    if not user:
        return None

    # Respect user push notification preference if configured
    pref = getattr(user, 'notification_preferences', None)
    if pref and not pref.enable_push_notifications:
        logger.info(f"[FCM] Push skipped for user {user.id}: disabled in preferences")
        return None

    fb_app = _get_initialized_firebase_app()
    if not _firebase_initialized:
        logger.info(f"[FCM] Push skipped for user {user.id}: Firebase not initialized")
        return None

    raw_tokens = list(
        DeviceToken.objects.filter(user=user, is_active=True).values_list('token', flat=True)
    )
    tokens = list(dict.fromkeys([t.strip() for t in raw_tokens if t and t.strip()]))

    if not tokens:
        logger.info(f"[FCM] No active device tokens for user {user.id}")
        return None

    data_payload = {str(k): str(v) for k, v in (extra_data or {}).items()}

    try:
        from firebase_admin import messaging
        message = messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data=data_payload,
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    sound='default',
                    channel_id='cagh_notifications',
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        sound='default',
                    ),
                ),
            ),
        )

        if hasattr(messaging, 'send_each_for_multicast'):
            response = messaging.send_each_for_multicast(message, app=fb_app)
        else:
            response = messaging.send_multicast(message, app=fb_app)

        if response.failure_count > 0:
            for idx, resp in enumerate(response.responses):
                if not resp.success:
                    exc = resp.exception
                    err_code = getattr(exc, 'code', None) or getattr(exc, 'error_code', None) or type(exc).__name__ if exc else "UNKNOWN_ERROR"
                    err_msg = str(exc) if exc else "No exception detail"

                    logger.error(
                        f"[FCM] Push token failed for user {user.id} index={idx} code={err_code} message={err_msg}"
                    )

                    err_str = f"{err_code} {err_msg}".lower()
                    if any(pattern in err_str for pattern in ['unregistered', 'invalid_argument', 'invalid-argument', 'not_found', 'not-found', 'sender_id_mismatch', 'sender-id-mismatch']):
                        stale_token = tokens[idx]
                        DeviceToken.objects.filter(token=stale_token).update(is_active=False)
                        logger.info(f"[FCM] Token deactivated for user {user.id} index={idx} code={err_code}")

        return response
    except Exception as exc:
        logger.error(f"[FCM] General push notification error for user {user.id}: {exc}")
        return None


