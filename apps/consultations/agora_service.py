import os
import time
import hashlib
import logging
from django.conf import settings
from agora_token_builder import RtcTokenBuilder

logger = logging.getLogger(__name__)


class Role:
    ATTENDEE = 0
    PUBLISHER = 1
    SUBSCRIBER = 2
    ADMIN = 101


class AgoraService:
    """
    Agora RTC Token Generation Service.
    Generates secure RTC access tokens using the official Agora SDK token builder.
    App Certificate is kept strictly server-side on Django and NEVER sent to Flutter clients.
    """

    @staticmethod
    def get_numeric_uid(user_id) -> int:
        if not user_id:
            return 0
        try:
            candidate = int(user_id)
        except (ValueError, TypeError):
            s = str(user_id).replace('-', '').lower()
            candidate = int(hashlib.md5(s.encode('utf-8')).hexdigest()[:8], 16)

        # Agora requires uid to fit in a 32-bit unsigned integer (max 4294967295).
        # Enforce this regardless of input size/type to prevent oversized UIDs
        # from ever reaching the token builder.
        safe_uid = candidate % 4294967295
        return safe_uid if safe_uid != 0 else 1

    @staticmethod
    def generate_rtc_token(
        channel_name: str,
        uid: int = 0,
        role: int = Role.PUBLISHER,
        expire_seconds: int = 3600
    ) -> str:
        """
        Generates a short-lived signed Agora RTC token for a given channel name and numeric user ID using RtcTokenBuilder.
        """
        app_id = getattr(settings, 'AGORA_APP_ID', os.environ.get('AGORA_APP_ID', ''))
        app_certificate = getattr(settings, 'AGORA_APP_CERTIFICATE', os.environ.get('AGORA_APP_CERTIFICATE', ''))

        if not channel_name:
            channel_name = "cagh_default_channel"

        current_ts = int(time.time())
        privilege_expired_ts = current_ts + expire_seconds

        numeric_uid = AgoraService.get_numeric_uid(uid)

        from django.core.exceptions import ImproperlyConfigured
        if not app_certificate or app_certificate == '':
            logger.error(f"[AGORA SERVICE ERROR] AGORA_APP_CERTIFICATE is not configured in settings or environment.")
            raise ImproperlyConfigured("AGORA_APP_CERTIFICATE is required for signed RTC token generation.")

        # Build official signed Agora RTC Access Token using official agora-token-builder
        try:
            token = RtcTokenBuilder.buildTokenWithUid(
                appId=app_id,
                appCertificate=app_certificate,
                channelName=channel_name,
                uid=numeric_uid,
                role=role,
                privilegeExpiredTs=privilege_expired_ts
            )
            logger.info(f"[AGORA DEBUG] token_prefix={token[:10] if token else None} | app_id={app_id} | uid={numeric_uid} | channel={channel_name} | role={role} | expires={privilege_expired_ts} | now={current_ts}")
            if not token:
                raise ValueError("RtcTokenBuilder.buildTokenWithUid returned empty or None token.")
            return token
        except Exception as e:
            logger.error(f"[AGORA SERVICE ERROR] Token generation failed: {e}", exc_info=True)
            raise

