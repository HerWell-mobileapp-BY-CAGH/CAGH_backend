"""
Admin portal URL routing — /api/v1/admin/

GET  /api/v1/admin/dashboard/                  — platform totals + recent activity
GET  /api/v1/admin/midwives/{profile_id}/stats/ — per-midwife consultation/appointment stats
"""

from django.urls import path

from .admin_views import (
    AdminDashboardView,
    AdminEmergencyContactListCreateView,
    AdminHospitalListCreateView,
    AdminMidwifeStatsView,
    AdminNotificationListCreateView,
)
from apps.users.views import AdminUserListCreateView

urlpatterns = [
    path("users/", AdminUserListCreateView.as_view(), name="admin-user-list-create"),
    path("notifications/", AdminNotificationListCreateView.as_view(), name="admin-notification-list-create"),
    path("emergency-contacts/", AdminEmergencyContactListCreateView.as_view(), name="admin-emergency-contact-list-create"),
    path("hospitals/", AdminHospitalListCreateView.as_view(), name="admin-hospital-list-create"),
    path("dashboard/", AdminDashboardView.as_view(), name="admin-dashboard"),
    path(
        "midwives/<uuid:pk>/stats/",
        AdminMidwifeStatsView.as_view(),
        name="admin-midwife-stats",
    ),
]
