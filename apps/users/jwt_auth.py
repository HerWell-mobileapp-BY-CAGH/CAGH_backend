"""JWT authentication helpers (standard SimpleJWT — no midwife login gate)."""

from rest_framework_simplejwt.authentication import JWTAuthentication


class MidwifeGateJWTAuthentication(JWTAuthentication):
    """
    Kept for backwards compatibility with older settings imports.
    Unapproved midwives may authenticate; booking/visibility rules enforce access.
    """

    pass
