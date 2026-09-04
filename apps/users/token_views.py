"""JWT token views."""

from rest_framework_simplejwt.views import TokenRefreshView


class MidwifeGateTokenRefreshView(TokenRefreshView):
    """
    Kept for backwards compatibility with older URL imports.
    Refresh is allowed for all active midwife accounts.
    """

    pass
