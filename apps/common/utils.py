import logging
from .models import AuditLog

logger = logging.getLogger(__name__)

def log_audit(user=None, action="", request=None, details=None):
    """
    Helper utility to record an AuditLog entry in the database.
    """
    try:
        ip_address = None
        if request:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0].strip()
            else:
                ip_address = request.META.get('REMOTE_ADDR')

            if not user and hasattr(request, 'user') and request.user and request.user.is_authenticated:
                user = request.user

        if user and not user.is_authenticated:
            user = None

        return AuditLog.objects.create(
            user=user,
            action=action[:255] if action else "UNKNOWN_ACTION",
            ip_address=ip_address,
            details=details or {},
        )
    except Exception as e:
        logger.error(f"Failed to create AuditLog entry: {e}")
        return None
