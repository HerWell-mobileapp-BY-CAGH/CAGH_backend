import os
import json
import socket
import logging
import urllib.request
import urllib.error
from django.core.mail.backends.smtp import EmailBackend as DjangoEmailBackend

logger = logging.getLogger(__name__)


class IPv4EmailBackend(DjangoEmailBackend):
    """
    Smart Email Backend for Render & Cloud deployments.
    Render blocks outbound raw SMTP ports (25, 465, 587) on free instances.
    This backend uses HTTPS API (Port 443) via Resend/Brevo if API key is present,
    or falls back to IPv4 SMTP on non-blocked hosts.
    """

    def send_messages(self, email_messages):
        resend_key = os.environ.get("RESEND_API_KEY", "").strip()
        brevo_key = os.environ.get("BREVO_API_KEY", "").strip()

        if resend_key or brevo_key:
            sent_count = 0
            for msg in email_messages:
                sent = False
                if resend_key:
                    try:
                        self._send_via_resend(msg, resend_key)
                        sent = True
                    except Exception as e:
                        logger.error(f"Resend HTTP API email send failed: {e}")

                if not sent and brevo_key:
                    try:
                        self._send_via_brevo(msg, brevo_key)
                        sent = True
                    except Exception as e:
                        logger.error(f"Brevo HTTP API email send failed: {e}")

                if sent:
                    sent_count += 1
                else:
                    logger.error("All HTTP API email services failed. Falling back to SMTP.")
                    try:
                        sent_count += super().send_messages([msg])
                    except Exception as smtp_err:
                        logger.error(f"Failed SMTP fallback email send: {smtp_err}")
                        if not self.fail_silently:
                            raise
            return sent_count

        return super().send_messages(email_messages)

    def _send_via_resend(self, msg, api_key):
        url = "https://api.resend.com/emails"
        from_addr = os.environ.get("RESEND_FROM_EMAIL", "").strip()
        if not from_addr:
            if msg.from_email and not msg.from_email.lower().endswith("@gmail.com"):
                from_addr = msg.from_email
            else:
                from_addr = "CAGH <onboarding@resend.dev>"

        payload = json.dumps({
            "from": from_addr,
            "to": msg.to,
            "subject": msg.subject,
            "text": msg.body,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status not in (200, 201):
                    raise RuntimeError(f"Resend HTTP status: {resp.status}")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Resend HTTP {e.code} error: {err_body}") from e

    def _send_via_brevo(self, msg, api_key):
        url = "https://api.brevo.com/v3/smtp/email"
        from_email = msg.from_email or os.environ.get("DEFAULT_FROM_EMAIL", "bitsuanabate45@gmail.com")
        payload = json.dumps({
            "sender": {"name": "CAGH", "email": from_email},
            "to": [{"email": recipient} for recipient in msg.to],
            "subject": msg.subject,
            "textContent": msg.body,
        }).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "accept": "application/json",
                "api-key": api_key,
                "content-type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status not in (200, 201):
                    raise RuntimeError(f"Brevo HTTP status: {resp.status}")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Brevo HTTP {e.code} error: {err_body}") from e

    def open(self):
        if self.connection:
            return False

        orig_getaddrinfo = socket.getaddrinfo

        def ipv4_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

        socket.getaddrinfo = ipv4_getaddrinfo
        try:
            return super().open()
        finally:
            socket.getaddrinfo = orig_getaddrinfo
