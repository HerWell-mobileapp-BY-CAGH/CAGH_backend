"""
Root URL configuration for CAGH backend.

All API routes are versioned under /api/v1/
Auth routes live at       /api/v1/auth/
OpenAPI docs live at      /api/docs/  and  /api/redoc/
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    # ------------------------------------------------------------------ Admin
    path("admin/", admin.site.urls),


    # --------------------------------------------------- OpenAPI / Swagger UI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),

    # ------------------------------------------------ API v1 Endpoints
    path("api/v1/auth/", include("apps.users.auth_urls")),
    path("api/v1/users/", include("apps.users.urls")),
    path("api/v1/midwives/", include("apps.midwives.urls")),
    path("api/v1/appointments/", include("apps.appointments.urls")),
    path("api/v1/consultations/", include("apps.consultations.urls")),
    path("api/v1/chat/", include("apps.chat.urls")),
    path("api/v1/notifications/", include("apps.notifications.urls")),
    path("api/v1/learning/", include("apps.learning.urls")),
    path("api/v1/reviews/", include("apps.reviews.urls")),
    path("api/v1/ai-assistant/", include("apps.ai_assistant.urls")),
    path("api/v1/common/", include("apps.common.urls")),
    path("api/v1/admin/", include("apps.common.admin_urls")),
]

# Serve media & static in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
