from .utils import log_audit

class AuditLogMiddleware:
    """
    Middleware to automatically record state-changing API operations (POST, PUT, PATCH, DELETE)
    and authentication endpoints into the AuditLog table.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Log state-changing requests or key auth paths
        if request.method in ['POST', 'PUT', 'PATCH', 'DELETE'] or '/api/v1/auth/' in request.path:
            # Avoid logging password strings or sensitive raw bodies
            action_name = f"{request.method} {request.path}"
            status_code = getattr(response, 'status_code', 200)

            user = getattr(request, 'user', None)
            if user and not user.is_authenticated:
                user = None

            details = {
                'status_code': status_code,
                'path': request.path,
                'method': request.method,
            }

            # Don't fail the request if logging encounters any issue
            try:
                log_audit(user=user, action=action_name, request=request, details=details)
            except Exception:
                pass

        return response
