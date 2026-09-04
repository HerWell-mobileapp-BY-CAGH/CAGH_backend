"""
Admin portal API views.

These endpoints are consumed exclusively by the React admin dashboard.
All routes require an authenticated administrator (role ADMIN + is_staff).
"""

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse

from apps.users.permissions import IsAdmin
from apps.midwives.models import MidwifeProfile
from .admin_services import (
    build_admin_dashboard_payload,
    build_midwife_stats_payload,
    DEFAULT_RECENT_ACTIVITY_LIMIT,
    DEFAULT_MIDWIFE_RECENT_LIMIT,
)
from .admin_serializers import (
    AdminDashboardResponseSerializer,
    AdminMidwifeStatsResponseSerializer,
)


class AdminDashboardView(APIView):
    """
    GET /api/v1/admin/dashboard/

    Returns platform-wide totals, status breakdowns, and a recency-sorted
    activity feed for the admin home screen.
    """

    permission_classes = [IsAdmin]

    @extend_schema(
        summary="Admin dashboard totals and recent activity",
        description=(
            "Provides aggregate counts for users, midwives, consultations, and "
            "appointments, including per-status breakdowns. Also returns the most "
            "recent audit-log entries for the admin activity feed."
        ),
        parameters=[
            OpenApiParameter(
                name="recent_limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    f"Maximum number of recent activity rows to return "
                    f"(default {DEFAULT_RECENT_ACTIVITY_LIMIT})."
                ),
            ),
        ],
        responses={200: AdminDashboardResponseSerializer},
        tags=["Admin Dashboard"],
    )
    def get(self, request):
        # Allow the frontend to request fewer/more activity rows without a new endpoint.
        try:
            recent_limit = int(request.query_params.get("recent_limit", DEFAULT_RECENT_ACTIVITY_LIMIT))
        except (TypeError, ValueError):
            recent_limit = DEFAULT_RECENT_ACTIVITY_LIMIT

        # Clamp to a sensible range so a malformed query cannot load the whole audit table.
        recent_limit = max(1, min(recent_limit, 50))

        payload = build_admin_dashboard_payload(recent_activity_limit=recent_limit)
        return Response(payload, status=status.HTTP_200_OK)


class AdminMidwifeStatsView(APIView):
    """
    GET /api/v1/admin/midwives/{profile_id}/stats/

    Returns consultation and appointment metrics for one midwife, including
    per-status counts and the most recent records. Used when an admin selects
    a midwife row in the dashboard table.
    """

    permission_classes = [IsAdmin]

    @extend_schema(
        summary="Consultation and appointment stats for one midwife",
        description=(
            "When an admin selects a midwife, this endpoint returns how many "
            "consultations and appointments belong to that midwife, broken down "
            "by status, plus the most recent records for quick review."
        ),
        parameters=[
            OpenApiParameter(
                name="recent_limit",
                type=int,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    f"Number of recent consultation/appointment rows per list "
                    f"(default {DEFAULT_MIDWIFE_RECENT_LIMIT})."
                ),
            ),
        ],
        responses={
            200: AdminMidwifeStatsResponseSerializer,
            404: OpenApiResponse(description="Midwife profile not found."),
        },
        tags=["Admin Dashboard"],
    )
    def get(self, request, pk):
        try:
            recent_limit = int(request.query_params.get("recent_limit", DEFAULT_MIDWIFE_RECENT_LIMIT))
        except (TypeError, ValueError):
            recent_limit = DEFAULT_MIDWIFE_RECENT_LIMIT

        recent_limit = max(1, min(recent_limit, 50))

        # pk is the MidwifeProfile UUID shown in admin midwife lists.
        try:
            midwife_profile = (
                MidwifeProfile.objects.select_related("user", "user__profile", "hospital")
                .get(pk=pk)
            )
        except MidwifeProfile.DoesNotExist:
            return Response(
                {"error": "Midwife profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        payload = build_midwife_stats_payload(midwife_profile, recent_limit=recent_limit)
        return Response(payload, status=status.HTTP_200_OK)
