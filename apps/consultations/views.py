import logging
from django.db import models
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema

from .models import Consultation, ConsultationNote
from .serializers import (
    ConsultationSerializer,
    ConsultationNoteSerializer,
)
from apps.appointments.models import Appointment
from apps.notifications.models import Notification


logger = logging.getLogger(__name__)


class ConsultationViewSet(viewsets.ModelViewSet):
    """
    Consultation Management ViewSet.
    Handles consultation state transitions, notes, and cellular call access controls.
    """

    queryset = Consultation.objects.all().select_related(
        'appointment', 'user', 'user__profile', 'midwife', 'midwife__user', 'midwife__user__profile', 'midwife__hospital'
    ).prefetch_related('notes')
    serializer_class = ConsultationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = Consultation.objects.all().select_related(
            'appointment', 'user', 'user__profile', 'midwife', 'midwife__user', 'midwife__user__profile', 'midwife__hospital'
        ).prefetch_related('notes')

        appointment_id = self.request.query_params.get('appointment') or self.request.query_params.get('appointment_id')
        if appointment_id:
            queryset = queryset.filter(appointment_id=appointment_id)

        if self.action in [
            'retrieve', 'add_note', 'complete', 'destroy',
            'call_midwife', 'call_midwife_alias', 'call_access', 'call_access_alias', 'call_eligibility', 'call_eligibility_alias'
        ]:
            return queryset

        if user.is_staff or getattr(user, 'role', '') == 'ADMIN':
            return queryset

        if hasattr(user, 'midwife_profile'):
            return queryset.filter(models.Q(user=user) | models.Q(midwife=user.midwife_profile))

        return queryset.filter(user=user)

    def create(self, request, *args, **kwargs):
        appointment_id = request.data.get('appointment')
        if appointment_id:
            existing = Consultation.objects.filter(appointment_id=appointment_id).first()
            if existing:
                serializer = self.get_serializer(existing)
                return Response(serializer.data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)

    def get_object(self):
        pk = self.kwargs.get('pk')
        consultation = Consultation.objects.filter(id=pk).first()

        if not consultation:
            appointment = Appointment.objects.filter(id=pk).first()
            if appointment:
                consultation = getattr(appointment, 'consultation', None)
                if not consultation:
                    consultation, _ = Consultation.objects.get_or_create(
                        appointment=appointment,
                        defaults={
                            'user': appointment.user,
                            'midwife': appointment.midwife,
                            'consultation_type': appointment.appointment_type,
                            'status': Consultation.ConsultationStatus.SCHEDULED,
                        }
                    )

        if not consultation:
            from rest_framework.exceptions import NotFound
            raise NotFound("No active consultation or appointment record found matching the provided ID.")

        self.check_object_permissions(self.request, consultation)
        return consultation

    def _get_consultation_and_verify_participant(self, request, pk):
        """
        Enforces strict participant authorization across consultation operations.
        Only consultation.user (Patient), consultation.midwife.user (Midwife), or Admin can perform operations.
        """
        consultation = self.get_object()
        user = request.user

        is_patient = (consultation.user_id == user.id)
        is_midwife = (
            (hasattr(user, 'midwife_profile') and consultation.midwife_id == user.midwife_profile.id) or
            (consultation.midwife and hasattr(consultation.midwife, 'user') and consultation.midwife.user_id == user.id)
        )
        is_admin = user.is_staff or getattr(user, 'role', '') == 'ADMIN'

        if not (is_patient or is_midwife or is_admin):
            raise PermissionDenied("You are not authorized to participate in this consultation operation.")

        return consultation, is_patient, is_midwife

    def perform_create(self, serializer):
        appointment = serializer.validated_data['appointment']

        if appointment.status != Appointment.AppointmentStatus.CONFIRMED:
            raise ValidationError({"appointment": "Consultation requires a confirmed appointment."})

        serializer.save(
            user=appointment.user,
            midwife=appointment.midwife,
            consultation_type=appointment.appointment_type,
            status=Consultation.ConsultationStatus.SCHEDULED,
        )

    def destroy(self, request, *args, **kwargs):
        return Response(
            {"error": "Consultation records cannot be permanently deleted due to medical audit trail policies."},
            status=status.HTTP_403_FORBIDDEN,
        )

    @extend_schema(summary="Get currently active consultation", tags=["Consultations"])
    @action(detail=False, methods=['get'])
    def active(self, request):
        queryset = self.get_queryset().filter(status__in=[Consultation.ConsultationStatus.ACTIVE, Consultation.ConsultationStatus.SCHEDULED])
        active_consultation = queryset.first()

        if not active_consultation:
            return Response({"active": False, "consultation": None}, status=status.HTTP_200_OK)

        serializer = self.get_serializer(active_consultation)
        return Response({"active": True, "consultation": serializer.data}, status=status.HTTP_200_OK)

    @extend_schema(summary="Get past consultation history", tags=["Consultations"])
    @action(detail=False, methods=['get'])
    def history(self, request):
        queryset = self.get_queryset().filter(status__in=[Consultation.ConsultationStatus.COMPLETED, Consultation.ConsultationStatus.CANCELLED])
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(summary="Complete consultation & record diagnosis/summary", tags=["Consultations"])
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        consultation, is_patient, is_midwife = self._get_consultation_and_verify_participant(request, pk)

        if is_midwife and hasattr(request.user, 'midwife_profile') and request.user.midwife_profile != consultation.midwife and not request.user.is_staff:
            return Response({'error': 'Only the assigned midwife can complete the consultation.'}, status=status.HTTP_403_FORBIDDEN)

        consultation.status = Consultation.ConsultationStatus.COMPLETED
        consultation.ended_at = timezone.now()
        consultation.summary = request.data.get('summary', consultation.summary)
        consultation.diagnosis = request.data.get('diagnosis', consultation.diagnosis)
        consultation.recommendation = request.data.get('recommendation', consultation.recommendation)
        consultation.follow_up_required = request.data.get('follow_up_required', consultation.follow_up_required)

        follow_up_date_str = request.data.get('follow_up_date')
        if follow_up_date_str:
            consultation.follow_up_date = follow_up_date_str

        consultation.save()

        if consultation.appointment:
            consultation.appointment.status = Appointment.AppointmentStatus.COMPLETED
            consultation.appointment.save(update_fields=['status'])

        Notification.objects.create(
            user=consultation.user,
            title="Consultation Completed",
            body=f"Your consultation with Midwife {consultation.midwife.user.username} has been completed. Summary & recommendations are now available.",
            type="CONSULTATION",
            action="CONSULTATION_COMPLETED",
            reference_id=str(consultation.id),
        )

        serializer = self.get_serializer(consultation)
        return Response({'status': 'COMPLETED', 'ended_at': consultation.ended_at, 'consultation': serializer.data}, status=status.HTTP_200_OK)

    @extend_schema(summary="Add consultation note (Assigned midwife only)", tags=["Consultations"])
    @action(detail=True, methods=['post'])
    def add_note(self, request, pk=None):
        consultation, is_patient, is_midwife = self._get_consultation_and_verify_participant(request, pk)

        if not is_midwife:
            return Response(
                {'error': 'Only the assigned midwife can add consultation notes.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        note_text = request.data.get('note')
        if not note_text:
            return Response({'error': 'Note content is required.'}, status=status.HTTP_400_BAD_REQUEST)

        note = ConsultationNote.objects.create(
            consultation=consultation,
            midwife=request.user.midwife_profile,
            note=note_text,
        )
        serializer = ConsultationNoteSerializer(note)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Call Midwife: Check eligibility and retrieve dialer tel URI", tags=["Consultations"])
    @action(detail=True, methods=['get', 'post'], url_path='call-midwife')
    def call_midwife(self, request, pk=None):
        consultation = self.get_object()
        appointment = getattr(consultation, 'appointment', None)
        if not appointment:
            return Response(
                {"error": "No appointment linked to this consultation record.", "can_call": False},
                status=status.HTTP_404_NOT_FOUND
            )

        from apps.appointments.call_service import AppointmentCallService
        data = AppointmentCallService.check_call_eligibility(appointment, request.user, request=request)
        data["consultation_id"] = str(consultation.id)

        if not data["is_authorized"]:
            return Response(
                {"error": "You do not have permission to access call details for this consultation.", "detail": data["reason"]},
                status=status.HTTP_403_FORBIDDEN
            )

        if request.method == 'POST' and not data["can_call"]:
            return Response(data, status=status.HTTP_400_BAD_REQUEST)

        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get', 'post'], url_path='call_midwife')
    def call_midwife_alias(self, request, pk=None):
        return self.call_midwife(request, pk=pk)

    @action(detail=True, methods=['get', 'post'], url_path='call-access')
    def call_access(self, request, pk=None):
        return self.call_midwife(request, pk=pk)

    @action(detail=True, methods=['get', 'post'], url_path='call_access')
    def call_access_alias(self, request, pk=None):
        return self.call_midwife(request, pk=pk)

    @action(detail=True, methods=['get'], url_path='call-eligibility')
    def call_eligibility(self, request, pk=None):
        return self.call_midwife(request, pk=pk)

    @action(detail=True, methods=['get'], url_path='call_eligibility')
    def call_eligibility_alias(self, request, pk=None):
        return self.call_midwife(request, pk=pk)
