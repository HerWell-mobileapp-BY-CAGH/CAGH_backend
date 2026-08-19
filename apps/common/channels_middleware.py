from urllib.parse import parse_qs
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError

User = get_user_model()


@database_sync_to_async
def get_user_from_token(token_string):
    """
    Decodes SimpleJWT access token and returns the corresponding User instance,
    or AnonymousUser if token is invalid or user does not exist.
    """
    try:
        validated_token = AccessToken(token_string)
        user_id = validated_token.get('user_id')
        if not user_id:
            return AnonymousUser()
        return User.objects.get(id=user_id)
    except (InvalidToken, TokenError, User.DoesNotExist):
        return AnonymousUser()


class JWTAuthMiddleware:
    """
    Custom Channels middleware to authenticate WebSocket connections using SimpleJWT access tokens.
    Supports token passing via:
    1. Query Parameter: ws://.../ws/chat/<room_id>/?token=<jwt_access_token>
    2. Authorization Header: Bearer <jwt_access_token>
    """

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        token = None

        # 1. Check query parameters
        query_string = scope.get('query_string', b'').decode('utf-8')
        query_params = parse_qs(query_string)
        if 'token' in query_params:
            token = query_params['token'][0]

        # 2. If not in query params, check headers for Authorization: Bearer <token>
        if not token and 'headers' in scope:
            headers = dict(scope.get('headers', []))
            auth_header = headers.get(b'authorization', b'').decode('utf-8')
            if auth_header.startswith('Bearer '):
                token = auth_header.split(' ')[1].strip()

        # 3. Authenticate user or fallback to AnonymousUser
        if token:
            scope['user'] = await get_user_from_token(token)
        elif 'user' not in scope or scope['user'].is_anonymous:
            scope['user'] = AnonymousUser()

        return await self.inner(scope, receive, send)


def JWTAuthMiddlewareStack(inner):
    return JWTAuthMiddleware(inner)
