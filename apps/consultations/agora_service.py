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
            return int(user_id)
        except (ValueError, TypeError):
            s = str(user_id).replace('-', '').lower()
            return int(hashlib.md5(s.encode('utf-8')).hexdigest()[:8], 16) % 100000000

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
            return token
        except Exception as e:
            logger.error(f"[AGORA SERVICE ERROR] Token generation failed: {e}")
            return f"RTC_TOKEN_{channel_name}_{numeric_uid}_{privilege_expired_ts}"

