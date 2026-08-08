from django.db import models
from django.utils import timezone
from rest_framework import viewsets, permissions, status, generics
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiResponse

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
)


class HospitalViewSet(viewsets.ModelViewSet):
    queryset = Hospital.objects.all()
    serializer_class = HospitalSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class MidwifeProfileViewSet(viewsets.ModelViewSet):
    """
    Midwife Profiles Management.
    FR-014: Registration & Qualifications
    FR-015: Admin Approval Workflow (APPROVE, REJECT, SUSPEND)
    """

    queryset = MidwifeProfile.objects.all()
    serializer_class = MidwifeProfileSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = MidwifeProfile.objects.select_related('user', 'hospital').prefetch_related('qualifications', 'certificates', 'expertises')
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
        try:
            profile = request.user.midwife_profile
        except MidwifeProfile.DoesNotExist:
            return Response(
                {"error": "Authenticated user does not have a midwife profile."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if request.method in ['PATCH', 'PUT']:
            serializer = self.get_serializer(profile, data=request.data, partial=(request.method == 'PATCH'))
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data)

        serializer = self.get_serializer(profile)
        return Response(serializer.data)

    @extend_schema(
        summary="Admin review and approval workflow for midwife accounts",
        description="Action types: APPROVE, REJECT, SUSPEND",
        tags=["Midwives"],
    )
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAdminUser])
    def verify(self, request, pk=None):
        midwife = self.get_object()
        action_type = request.data.get('action')  # APPROVE, REJECT, SUSPEND

        if action_type == 'APPROVE':
            midwife.verification_status = MidwifeProfile.VerificationStatus.APPROVED
            midwife.verified_at = timezone.now()
            midwife.verified_by = request.user
            midwife.rejection_reason = ''
            midwife.save()
            return Response({'status': 'Midwife account approved successfully.'}, status=status.HTTP_200_OK)

        elif action_type == 'REJECT':
            midwife.verification_status = MidwifeProfile.VerificationStatus.REJECTED
            midwife.rejection_reason = request.data.get('reason', '')
            midwife.save()
            return Response({'status': 'Midwife account rejected.'}, status=status.HTTP_200_OK)

        elif action_type == 'SUSPEND':
            midwife.verification_status = MidwifeProfile.VerificationStatus.SUSPENDED
            midwife.save()
            return Response({'status': 'Midwife account suspended.'}, status=status.HTTP_200_OK)

        return Response(
            {'error': 'Invalid action. Allowed values: APPROVE, REJECT, SUSPEND.'},
            status=status.HTTP_400_BAD_REQUEST,
        )


class QualificationViewSet(viewsets.ModelViewSet):
    serializer_class = QualificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if hasattr(self.request.user, 'midwife_profile'):
            return Qualification.objects.filter(midwife=self.request.user.midwife_profile)
        return Qualification.objects.none()

    def perform_create(self, serializer):
        if hasattr(self.request.user, 'midwife_profile'):
            serializer.save(midwife=self.request.user.midwife_profile)


class CertificateViewSet(viewsets.ModelViewSet):
    serializer_class = CertificateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if hasattr(self.request.user, 'midwife_profile'):
            return Certificate.objects.filter(midwife=self.request.user.midwife_profile)
        return Certificate.objects.none()

    def perform_create(self, serializer):
        if hasattr(self.request.user, 'midwife_profile'):
            serializer.save(midwife=self.request.user.midwife_profile)


class BlockedDateViewSet(viewsets.ModelViewSet):
    """
    FR-017: Midwife Blocked Dates (Leave / Holidays).
    """

    serializer_class = BlockedDateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if hasattr(self.request.user, 'midwife_profile'):
            return BlockedDate.objects.filter(midwife=self.request.user.midwife_profile)
        return BlockedDate.objects.none()

    def perform_create(self, serializer):
        if hasattr(self.request.user, 'midwife_profile'):
            serializer.save(midwife=self.request.user.midwife_profile)


class SavedMidwifeViewSet(viewsets.ModelViewSet):
    serializer_class = SavedMidwifeSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SavedMidwife.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class MidwifeDashboardView(generics.GenericAPIView):
    """
    FR-016: Centralized Midwife Dashboard.
    Provides today's schedule, upcoming appointments, pending requests, recent history, and status stats.
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

