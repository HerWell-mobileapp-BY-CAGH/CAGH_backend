from django.db import models
from django.utils import timezone
from rest_framework import viewsets, permissions, status, generics, exceptions
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiResponse

from apps.common.utils import log_audit
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
        user = request.user
        if getattr(user, 'role', '') != 'MIDWIFE' and not hasattr(user, 'midwife_profile'):
            return Response(
                {"error": "Authenticated user is registered as a PATIENT, not a MIDWIFE. Only midwife accounts have a midwife profile."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        import uuid
        profile, _ = MidwifeProfile.objects.get_or_create(
            user=user,
            defaults={
                "license_number": f"LIC-{uuid.uuid4().hex[:8].upper()}",
                "verification_status": MidwifeProfile.VerificationStatus.PENDING,
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
            log_audit(user=request.user, action="MIDWIFE_VERIFY_APPROVE", request=request, details={"midwife_id": str(midwife.id)})
            return Response({'status': 'Midwife account approved successfully.'}, status=status.HTTP_200_OK)

        elif action_type == 'REJECT':
            midwife.verification_status = MidwifeProfile.VerificationStatus.REJECTED
            midwife.rejection_reason = request.data.get('reason', '')
            midwife.save()
            log_audit(user=request.user, action="MIDWIFE_VERIFY_REJECT", request=request, details={"midwife_id": str(midwife.id), "reason": midwife.rejection_reason})
            return Response({'status': 'Midwife account rejected.'}, status=status.HTTP_200_OK)

        elif action_type == 'SUSPEND':
            midwife.verification_status = MidwifeProfile.VerificationStatus.SUSPENDED
            midwife.save()
            log_audit(user=request.user, action="MIDWIFE_VERIFY_SUSPEND", request=request, details={"midwife_id": str(midwife.id)})
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
    FR-017: Midwife Blocked Dates (Leave / Holidays).
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

