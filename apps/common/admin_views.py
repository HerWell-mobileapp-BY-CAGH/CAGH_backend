"""
Admin portal API views.

These endpoints are consumed exclusively by the React admin dashboard.
All routes require an authenticated administrator (role ADMIN + is_staff).
"""

from rest_framework import filters, generics, status
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend

from apps.users.permissions import IsAdmin
from apps.users.models import EmergencyContact
from apps.notifications.models import Notification
from apps.midwives.models import MidwifeProfile
from apps.midwives.models import Hospital
from .admin_services import (
    build_admin_dashboard_payload,
    build_midwife_stats_payload,
    DEFAULT_RECENT_ACTIVITY_LIMIT,
    DEFAULT_MIDWIFE_RECENT_LIMIT,
)
from .admin_serializers import (
    AdminEmergencyContactSerializer,
    AdminDashboardResponseSerializer,
    AdminHospitalSerializer,
    AdminMidwifeStatsResponseSerializer,
    AdminNotificationSerializer,
)


class AdminListCreateView(generics.ListCreateAPIView):
    """Shared safeguards and query support for admin-managed collections."""

    permission_classes = [IsAdmin]
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)


class AdminNotificationListCreateView(AdminListCreateView):
    queryset = Notification.objects.select_related("user").all()
    serializer_class = AdminNotificationSerializer
    filterset_fields = ("user", "type", "is_read")
    search_fields = ("title", "body", "action", "reference_id", "user__username", "user__email")
    ordering_fields = ("created_at", "title", "type")
    ordering = ("-created_at",)

    @extend_schema(
        summary="List notifications",
        description="Admin-only notification list. Filter by `user`, `type`, or `is_read`; search notification content with `search`.",
        tags=["Admin"],
    )
    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    @extend_schema(
        summary="Send a notification to a user",
        description="Admin-only. Requires `user_id`, `title`, `body`, and `type`. Optional: `action`, `reference_id`.",
        tags=["Admin"],
    )
    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)


class AdminEmergencyContactListCreateView(AdminListCreateView):
    queryset = EmergencyContact.objects.select_related("user").all()
    serializer_class = AdminEmergencyContactSerializer
    filterset_fields = ("user", "is_primary")
    search_fields = ("name", "relationship", "phone_number", "user__username", "user__email")
    ordering_fields = ("name", "relationship", "is_primary")
    ordering = ("user__username", "-is_primary", "name")

    @extend_schema(
        summary="List all emergency contacts",
        description="Admin-only. Filter by `user` or `is_primary`; use `search` for contact or owner details.",
        tags=["Admin"],
    )
    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    @extend_schema(
        summary="Create an emergency contact for a user",
        description="Admin-only. Requires `user_id`, `name`, `relationship`, and `phone_number`.",
        tags=["Admin"],
    )
    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)


class AdminHospitalListCreateView(AdminListCreateView):
    # Annotate once so the dashboard's hospital table can display linked midwives.
    queryset = Hospital.objects.annotate(midwife_count=Count("midwives"))
    serializer_class = AdminHospitalSerializer
    search_fields = ("name", "address", "phone")
    ordering_fields = ("name", "created_at", "updated_at")
    ordering = ("name",)

    @extend_schema(
        summary="List hospitals",
        description="Admin-only hospital list. Supports `search` and `ordering`.",
        tags=["Admin"],
    )
    def get(self, request, *args, **kwargs):
        return self.list(request, *args, **kwargs)

    @extend_schema(
        summary="Create a hospital",
        description="Admin-only. Requires `name`, `address`, and `phone`; optional `latitude` and `longitude`.",
        tags=["Admin"],
    )
    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)


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
