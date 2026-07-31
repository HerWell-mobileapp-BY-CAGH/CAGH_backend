"""
Users module URL routing — /api/v1/users/

GET    /api/v1/users/me/                        — current user detail
PUT    /api/v1/users/me/                        — replace current user fields
PATCH  /api/v1/users/me/                        — partial update current user

GET    /api/v1/users/me/preferences/            — get notification/theme prefs
PATCH  /api/v1/users/me/preferences/            — update preferences

GET    /api/v1/users/profiles/                  — list own profile(s)
POST   /api/v1/users/profiles/                  — create profile
GET    /api/v1/users/profiles/{id}/             — retrieve
PATCH  /api/v1/users/profiles/{id}/             — update
DELETE /api/v1/users/profiles/{id}/             — delete

GET    /api/v1/users/emergency-contacts/        — list contacts
POST   /api/v1/users/emergency-contacts/        — add contact
...etc (standard ModelViewSet CRUD)

GET    /api/v1/users/sos/                       — list SOS logs
POST   /api/v1/users/sos/                       — trigger SOS event
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import (
    UserMeView,
    UserPreferenceView,
    ProfileViewSet,
    EmergencyContactViewSet,
    SOSLogViewSet,
)

router = DefaultRouter()
router.register(r"profiles", ProfileViewSet, basename="profile")
router.register(r"emergency-contacts", EmergencyContactViewSet, basename="emergency-contact")
router.register(r"sos", SOSLogViewSet, basename="sos-log")

urlpatterns = [
    path("me/", UserMeView.as_view(), name="user-me"),
    path("me/preferences/", UserPreferenceView.as_view(), name="user-preferences"),
    path("", include(router.urls)),
]
