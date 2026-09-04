"""
Admin portal URL routing — /api/v1/admin/

GET  /api/v1/admin/dashboard/                  — platform totals + recent activity
GET  /api/v1/admin/midwives/{profile_id}/stats/ — per-midwife consultation/appointment stats
"""

from django.urls import path

from .admin_views import AdminDashboardView, AdminMidwifeStatsView

urlpatterns = [
    path("dashboard/", AdminDashboardView.as_view(), name="admin-dashboard"),
    path(
        "midwives/<uuid:pk>/stats/",
        AdminMidwifeStatsView.as_view(),
        name="admin-midwife-stats",
    ),
]
