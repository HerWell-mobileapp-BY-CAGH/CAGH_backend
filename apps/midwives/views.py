from django.db import models
from django.utils import timezone
from rest_framework import viewsets, permissions, status, generics, exceptions
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView
from drf_spectacular.utils import extend_schema, OpenApiResponse

from apps.common.utils import log_audit
from apps.users.permissions import IsAdmin
from .models import Hospital, MidwifeProfile, Qualification, Certificate, Expertise, SavedMidwife, BlockedDate
from .serializers import (
    HospitalSerializer,
    MidwifeProfileSerializer,
    QualificationSerializer,
    CertificateSerializer,
    ExpertiseSerializer,
    SavedMidwifeSerializer,
    BlockedDateSerializer,
    MidwifeDashboardSerializer,
    MidwifeApplicationDetailSerializer,
    AdminMidwifeApplicationUpdateSerializer,
    MidwifeReviewActionSerializer,
)
from .utils import notify_midwife_review_result


def _apply_midwife_review(*, midwife, admin_user, action_type, reason="", request=None):
    """Apply an admin review decision and return a response payload."""
    if action_type == "APPROVE":
        midwife.verification_status = MidwifeProfile.VerificationStatus.APPROVED
        midwife.verified_at = timezone.now()
        midwife.verified_by = admin_user
        midwife.rejection_reason = ""
        midwife.suspension_reason = ""
        midwife.is_accepting_bookings = True
        midwife.save()
        notify_midwife_review_result(midwife, approved=True)
        log_audit(
            user=admin_user,
            action="MIDWIFE_VERIFY_APPROVE",
            request=request,
            details={"midwife_id": str(midwife.id)},
        )
        return {
            "status": "APPROVED",
            "message": "Midwife account approved successfully.",
            "verification_status": midwife.verification_status,
        }

    if action_type == "REJECT":
        midwife.verification_status = MidwifeProfile.VerificationStatus.REJECTED
        midwife.rejection_reason = reason.strip()
        midwife.verified_at = None
        midwife.verified_by = admin_user
        midwife.is_accepting_bookings = False
        midwife.save()
        notify_midwife_review_result(midwife, rejected=True, reason=midwife.rejection_reason)
        log_audit(
            user=admin_user,
            action="MIDWIFE_VERIFY_REJECT",
            request=request,
            details={"midwife_id": str(midwife.id), "reason": midwife.rejection_reason},
        )
        return {
            "status": "REJECTED",
            "message": "Midwife application rejected.",
            "verification_status": midwife.verification_status,
            "rejection_reason": midwife.rejection_reason,
        }

    if action_type == "SUSPEND":
        midwife.verification_status = MidwifeProfile.VerificationStatus.SUSPENDED
        midwife.suspension_reason = reason.strip()
        midwife.verified_by = admin_user
        midwife.is_accepting_bookings = False
        midwife.save()
        notify_midwife_review_result(midwife, suspended=True, reason=midwife.suspension_reason)
        log_audit(
            user=admin_user,
            action="MIDWIFE_VERIFY_SUSPEND",
            request=request,
            details={"midwife_id": str(midwife.id), "reason": midwife.suspension_reason},
        )
        return {
            "status": "SUSPENDED",
            "message": "Midwife account suspended.",
            "verification_status": midwife.verification_status,
            "suspension_reason": midwife.suspension_reason,
        }

    return None


class HospitalViewSet(viewsets.ModelViewSet):
    queryset = Hospital.objects.all()
    serializer_class = HospitalSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class MidwifeProfileViewSet(viewsets.ModelViewSet):
    """
    Manages midwife profile registrations, qualifications, and admin approval workflows.
    """

    queryset = MidwifeProfile.objects.all()
    serializer_class = MidwifeProfileSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = MidwifeProfile.objects.select_related('user', 'user__profile', 'user__preferences', 'user__midwife_profile', 'hospital').prefetch_related('qualifications', 'certificates', 'expertises')
        user = self.request.user

        # Admins see all profiles
        if user and user.is_authenticated and (user.is_staff or getattr(user, 'role', '') == 'ADMIN'):
            status_param = self.request.query_params.get('status')
            if status_param:
                queryset = queryset.filter(verification_status=status_param)
            return queryset

        # Midwives can see approved midwives plus their own profile
        if user and user.is_authenticated and getattr(user, 'role', '') == 'MIDWIFE':
            return queryset.filter(
                models.Q(verification_status=MidwifeProfile.VerificationStatus.APPROVED) |
                models.Q(user=user)
            )

        # Public / Patients only see APPROVED midwives
        queryset = queryset.filter(verification_status=MidwifeProfile.VerificationStatus.APPROVED)

        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                models.Q(user__first_name__icontains=search) |
                models.Q(user__last_name__icontains=search) |
                models.Q(user__username__icontains=search) |
                models.Q(specialty__icontains=search) |
                models.Q(hospital__name__icontains=search) |
                models.Q(expertises__name__icontains=search)
            ).distinct()

        return queryset

    @extend_schema(summary="Toggle midwife favorite/saved status", tags=["Midwives"])
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def favorite(self, request, pk=None):
        midwife = self.get_object()
        saved, created = SavedMidwife.objects.get_or_create(user=request.user, midwife=midwife)
        if not created:
            saved.delete()
            return Response({'is_favorite': False, 'message': 'Removed from favorites.'}, status=status.HTTP_200_OK)
        return Response({'is_favorite': True, 'message': 'Added to favorites.'}, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Get or update authenticated midwife's own profile", tags=["Midwives"])
    @action(detail=False, methods=['get', 'patch', 'put'], permission_classes=[permissions.IsAuthenticated])
    def me(self, request):
        user = request.user
        if getattr(user, 'role', '') != 'MIDWIFE' and not hasattr(user, 'midwife_profile'):
            return Response(
                {"error": "Authenticated user is registered as a PATIENT, not a MIDWIFE. Only midwife accounts have a midwife profile."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        profile, _ = MidwifeProfile.objects.get_or_create(
            user=user,
            defaults={
                "verification_status": MidwifeProfile.VerificationStatus.PENDING,
                "is_accepting_bookings": False,
            }
        )

        if request.method in ['PATCH', 'PUT']:
            serializer = self.get_serializer(profile, data=request.data, partial=(request.method == 'PATCH'), context={'request': request})
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

        serializer = self.get_serializer(profile, context={'request': request})
        return Response(serializer.data)

    @extend_schema(
        summary="Admin review and approval workflow for midwife accounts",
        description="Action types: APPROVE, REJECT (requires reason), SUSPEND (requires reason)",
        request=MidwifeReviewActionSerializer,
        tags=["Midwives"],
    )
    @action(detail=True, methods=['post'], permission_classes=[IsAdmin])
    def verify(self, request, pk=None):
        midwife = self.get_object()
        serializer = MidwifeReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action_type = serializer.validated_data["action"]
        reason = serializer.validated_data.get("reason", "")

        if action_type == "REJECT" and midwife.verification_status == MidwifeProfile.VerificationStatus.APPROVED:
            return Response(
                {"error": "Use SUSPEND to disable an already approved midwife account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = _apply_midwife_review(
            midwife=midwife,
            admin_user=request.user,
            action_type=action_type,
            reason=reason,
            request=request,
        )
        if result is None:
            return Response(
                {'error': 'Invalid action. Allowed values: APPROVE, REJECT, SUSPEND.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(result, status=status.HTTP_200_OK)


class QualificationViewSet(viewsets.ModelViewSet):
    serializer_class = QualificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if hasattr(self.request.user, 'midwife_profile'):
            return Qualification.objects.filter(midwife=self.request.user.midwife_profile)
        if self.request.user.is_staff or getattr(self.request.user, 'role', '') == 'ADMIN':
            return Qualification.objects.all()
        return Qualification.objects.none()

    def perform_create(self, serializer):
        if hasattr(self.request.user, 'midwife_profile'):
            serializer.save(midwife=self.request.user.midwife_profile)
        else:
            raise exceptions.PermissionDenied("Only registered midwives can add qualifications.")


class CertificateViewSet(viewsets.ModelViewSet):
    serializer_class = CertificateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if hasattr(self.request.user, 'midwife_profile'):
            return Certificate.objects.filter(midwife=self.request.user.midwife_profile)
        if self.request.user.is_staff or getattr(self.request.user, 'role', '') == 'ADMIN':
            return Certificate.objects.all()
        return Certificate.objects.none()

    def perform_create(self, serializer):
        if hasattr(self.request.user, 'midwife_profile'):
            serializer.save(midwife=self.request.user.midwife_profile)
        else:
            raise exceptions.PermissionDenied("Only registered midwives can add certificates.")


class ExpertiseViewSet(viewsets.ModelViewSet):
    queryset = Expertise.objects.all()
    serializer_class = ExpertiseSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class BlockedDateViewSet(viewsets.ModelViewSet):
    """
    Manages midwife blocked dates (leave and holidays).
    """

    serializer_class = BlockedDateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if hasattr(self.request.user, 'midwife_profile'):
            return BlockedDate.objects.filter(midwife=self.request.user.midwife_profile)
        if self.request.user.is_staff or getattr(self.request.user, 'role', '') == 'ADMIN':
            return BlockedDate.objects.all()
        return BlockedDate.objects.none()

    def perform_create(self, serializer):
        user = self.request.user
        if hasattr(user, 'midwife_profile'):
            if user.midwife_profile.verification_status != MidwifeProfile.VerificationStatus.APPROVED and not user.is_staff:
                raise exceptions.PermissionDenied("Your midwife account is awaiting admin verification before you can manage blocked dates.")
            serializer.save(midwife=user.midwife_profile)
        else:
            raise exceptions.PermissionDenied("Only registered midwives can manage blocked dates.")


class SavedMidwifeViewSet(viewsets.ModelViewSet):
    serializer_class = SavedMidwifeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SavedMidwife.objects.filter(user=self.request.user).select_related(
            'midwife', 'midwife__user', 'midwife__user__profile', 'midwife__user__preferences', 'midwife__user__midwife_profile', 'midwife__hospital'
        ).prefetch_related('midwife__qualifications', 'midwife__certificates', 'midwife__expertises')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class MidwifeDashboardView(generics.GenericAPIView):
    """
    Provides today's schedule, upcoming appointments, pending requests, recent history, and status statistics for midwives.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = MidwifeDashboardSerializer

    @extend_schema(summary="Get Midwife Dashboard Overview", tags=["Midwives"])
    def get(self, request):
        try:
            midwife = request.user.midwife_profile
        except MidwifeProfile.DoesNotExist:
            return Response(
                {"error": "Only registered midwives can access the dashboard."},
                status=status.HTTP_403_FORBIDDEN,
            )

        today = timezone.now().date()
        from apps.appointments.models import Appointment

        appointments = Appointment.objects.filter(midwife=midwife)

        today_schedule = list(
            appointments.filter(scheduled_date=today)
            .values("id", "appointment_number", "appointment_type", "start_time", "end_time", "status", "user__username", "user__email")
        )

        upcoming_appointments = list(
            appointments.filter(scheduled_date__gt=today, status__in=["CONFIRMED", "PENDING"])
            .order_by("scheduled_date", "start_time")[:10]
            .values("id", "appointment_number", "appointment_type", "scheduled_date", "start_time", "end_time", "status", "user__username")
        )

        pending_requests = list(
            appointments.filter(status="PENDING")
            .order_by("created_at")[:10]
            .values("id", "appointment_number", "appointment_type", "scheduled_date", "start_time", "end_time", "user__username", "reason")
        )

        recent_history = list(
            appointments.filter(status__in=["COMPLETED", "CANCELLED", "REJECTED", "MISSED"])
            .order_by("-updated_at")[:10]
            .values("id", "appointment_number", "appointment_type", "scheduled_date", "status", "user__username")
        )

        counts = {
            "pending": appointments.filter(status="PENDING").count(),
            "confirmed": appointments.filter(status="CONFIRMED").count(),
            "completed": appointments.filter(status="COMPLETED").count(),
            "cancelled": appointments.filter(status="CANCELLED").count(),
            "today_total": len(today_schedule),
        }

        data = {
            "verification_status": midwife.verification_status,
            "today_schedule": today_schedule,
            "upcoming_appointments": upcoming_appointments,
            "pending_requests": pending_requests,
            "recent_history": recent_history,
            "counts": counts,
        }

        return Response(data, status=status.HTTP_200_OK)


class MidwifeApplicationListView(generics.ListAPIView):
    """
    Admin-only list of midwife applications awaiting review.
    Returns full registration details for each pending application.
    """

    serializer_class = MidwifeApplicationDetailSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        queryset = (
            MidwifeProfile.objects.select_related("user", "user__profile", "hospital", "verified_by")
            .prefetch_related("qualifications", "certificates", "expertises")
            .order_by("created_at")
        )

        status_param = self.request.query_params.get("status")
        if status_param:
            return queryset.filter(verification_status=status_param)

        return queryset.filter(
            verification_status__in=[
                MidwifeProfile.VerificationStatus.PENDING,
                MidwifeProfile.VerificationStatus.UNDER_REVIEW,
            ]
        )

    @extend_schema(
        summary="List midwife applications pending admin review",
        description=(
            "Admin-only. Returns all submitted midwife registration details. "
            "Defaults to PENDING and UNDER_REVIEW applications."
        ),
        tags=["Midwives"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class MidwifeApplicationDetailView(generics.RetrieveUpdateAPIView):
    """Admin-only application review and credential-completion endpoint."""

    serializer_class = MidwifeApplicationDetailSerializer
    permission_classes = [IsAdmin]
    lookup_field = "pk"

    def get_queryset(self):
        return (
            MidwifeProfile.objects.select_related("user", "user__profile", "hospital", "verified_by")
            .prefetch_related("qualifications", "certificates", "expertises")
        )

    def get_serializer_class(self):
        return AdminMidwifeApplicationUpdateSerializer if self.request.method == "PATCH" else MidwifeApplicationDetailSerializer

    @extend_schema(
        summary="Retrieve full midwife application details for admin review",
        tags=["Midwives"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Complete or correct a midwife application",
        description="Admin-only multipart PATCH. Upload `cv_file` and/or set `license_number`, `hospital_id`, `bio`, `experience_years`, `specialty`, and `languages` before approval.",
        request=AdminMidwifeApplicationUpdateSerializer,
        responses={200: MidwifeApplicationDetailSerializer},
        tags=["Midwives"],
    )
    def patch(self, request, *args, **kwargs):
        application = self.get_object()
        serializer = self.get_serializer(application, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        # Audit which credentials were manually supplied, not file contents.
        log_audit(
            user=request.user,
            action="MIDWIFE_APPLICATION_DETAILS_UPDATED",
            request=request,
            details={"midwife_id": str(application.id), "updated_fields": list(serializer.validated_data.keys())},
        )
        return Response(MidwifeApplicationDetailSerializer(application, context={"request": request}).data)


class MidwifeApplicationReviewView(APIView):
    """Admin-only approve/reject endpoint for midwife applications."""

    permission_classes = [IsAdmin]

    @extend_schema(
        summary="Approve or reject a midwife application",
        request=MidwifeReviewActionSerializer,
        tags=["Midwives"],
    )
    def post(self, request, pk):
        try:
            midwife = (
                MidwifeProfile.objects.select_related("user")
                .prefetch_related("qualifications", "certificates", "expertises")
                .get(pk=pk)
            )
        except MidwifeProfile.DoesNotExist:
            return Response({"error": "Midwife application not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = MidwifeReviewActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        action_type = serializer.validated_data["action"]
        reason = serializer.validated_data.get("reason", "")

        if action_type == "REJECT" and midwife.verification_status == MidwifeProfile.VerificationStatus.APPROVED:
            return Response(
                {"error": "Use SUSPEND to disable an already approved midwife account."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        result = _apply_midwife_review(
            midwife=midwife,
            admin_user=request.user,
            action_type=action_type,
            reason=reason,
            request=request,
        )
        if result is None:
            return Response(
                {"error": "Invalid action. Allowed values: APPROVE, REJECT, SUSPEND."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        detail = MidwifeApplicationDetailSerializer(midwife, context={"request": request}).data
        return Response({**result, "application": detail}, status=status.HTTP_200_OK)

