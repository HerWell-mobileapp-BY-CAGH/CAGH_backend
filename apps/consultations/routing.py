from django.urls import re_path
from .consumers import ConsultationCallConsumer

websocket_urlpatterns = [
    re_path(r'^/?ws/consultation/(?P<consultation_id>[^/]+)/$', ConsultationCallConsumer.as_asgi()),
]
