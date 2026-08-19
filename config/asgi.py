import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')

django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter
from apps.common.channels_middleware import JWTAuthMiddlewareStack

from apps.chat.routing import websocket_urlpatterns as chat_ws_urlpatterns
from apps.consultations.routing import websocket_urlpatterns as consultation_ws_urlpatterns

all_websocket_urlpatterns = chat_ws_urlpatterns + consultation_ws_urlpatterns

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": JWTAuthMiddlewareStack(
        URLRouter(all_websocket_urlpatterns)
    ),
})



