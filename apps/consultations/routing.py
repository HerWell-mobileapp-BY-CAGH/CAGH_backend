from django.urls import re_path
from .consumers import ConsultationCallConsumer, UserCallConsumer

websocket_urlpatterns = [
    re_path(r'^/?ws/user-calls/$', UserCallConsumer.as_asgi()),
    re_path(r'^/?ws/consultation/(?P<consultation_id>[^/]+)/$', ConsultationCallConsumer.as_asgi()),
]
