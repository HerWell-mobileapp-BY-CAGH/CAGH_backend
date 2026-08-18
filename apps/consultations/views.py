import uuid
from django.db import models
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import Consultation, ConsultationNote, VoiceSession, VideoSession
from .serializers import (
    ConsultationSerializer,
    ConsultationNoteSerializer,
    VoiceSessionSerializer,
    VideoSessionSerializer,
)
from apps.appointments.models import Appointment
from apps.notifications.models import Notification
from apps.notifications.call_notifications import send_incoming_call_notification


class ConsultationViewSet(viewsets.ModelViewSet):
    """
    Module 4 — Consultation Management
    Enforces all SRS business rules and virtual call session lifecycle.
    """

    queryset = Consultation.objects.all().select_related('appointment', 'user', 'midwife', 'midwife__user').prefetch_related('notes')
    serializer_class = ConsultationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = Consultation.objects.all().select_related('appointment', 'user', 'midwife', 'midwife__user').prefetch_related('notes')

        if self.action in ['retrieve', 'add_note', 'start', 'complete', 'manage_voice_session', 'manage_video_session', 'destroy']:
            return queryset

        if user.is_staff or getattr(user, 'role', '') == 'ADMIN':
            return queryset

        if hasattr(user, 'midwife_profile'):
            return queryset.filter(models.Q(user=user) | models.Q(midwife=user.midwife_profile))

        return queryset.filter(user=user)


    def perform_create(self, serializer):
        appointment = serializer.validated_data['appointment']

        # Rule 2: Consultation requires a confirmed appointment
        if appointment.status != Appointment.AppointmentStatus.CONFIRMED:
            raise serializers.ValidationError({"appointment": "Consultation requires a confirmed appointment."})

        serializer.save(
            user=appointment.user,
            midwife=appointment.midwife,
            consultation_type=appointment.appointment_type,
            status=Consultation.ConsultationStatus.SCHEDULED,
        )

    def destroy(self, request, *args, **kwargs):
        # Rule 4: Consultation records cannot be permanently deleted
        return Response(
            {"error": "Consultation records cannot be permanently deleted due to medical audit trail policies."},
            status=status.HTTP_403_FORBIDDEN,
        )

    @extend_schema(summary="Get currently active consultation", tags=["Consultations"])
    @action(detail=False, methods=['get'])
    def active(self, request):
        user = request.user
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

    @extend_schema(summary="Start consultation lifecycle & trigger device call ringing", tags=["Consultations"])
    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        consultation = self.get_object()

        if consultation.status == Consultation.ConsultationStatus.COMPLETED:
            return Response({"error": "Completed consultations cannot be restarted."}, status=status.HTTP_400_BAD_REQUEST)

        consultation.status = Consultation.ConsultationStatus.ACTIVE
        if not consultation.started_at:
            consultation.started_at = timezone.now()
        consultation.save()

        session_key = None
        call_type = "VOICE"
        # Automatically initiate Voice or Video session if virtual consultation type
        if consultation.consultation_type == Consultation.ConsultationType.VIRTUAL_VOICE or consultation.consultation_type == 'VIRTUAL_VOICE':
            session, _ = VoiceSession.objects.get_or_create(
                consultation=consultation,
                defaults={"session_key": f"VOICE-{uuid.uuid4().hex[:12].upper()}", "status": VoiceSession.VoiceSessionStatus.INITIATED}
            )
            session_key = session.session_key
            call_type = "VOICE"
        elif consultation.consultation_type == Consultation.ConsultationType.VIRTUAL_VIDEO or consultation.consultation_type == 'VIRTUAL_VIDEO':
            session, _ = VideoSession.objects.get_or_create(
                consultation=consultation,
                defaults={"session_key": f"VIDEO-{uuid.uuid4().hex[:12].upper()}", "status": VideoSession.VideoSessionStatus.INITIATED}
            )
            session_key = session.session_key
            call_type = "VIDEO"

        # Determine caller vs recipient
        caller = request.user
        recipient = consultation.user if (hasattr(caller, 'midwife_profile') and caller.midwife_profile == consultation.midwife) else consultation.midwife.user

        # Trigger incoming call push notification to ring peer device
        send_incoming_call_notification(caller=caller, recipient=recipient, consultation=consultation, call_type=call_type, session_key=session_key)

        serializer = self.get_serializer(consultation)
        return Response({'status': 'ACTIVE', 'started_at': consultation.started_at, 'consultation': serializer.data}, status=status.HTTP_200_OK)

    @extend_schema(summary="Complete consultation & record diagnosis/summary", tags=["Consultations"])
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        consultation = self.get_object()

        # Rule 3 Check: Assigned midwife or admin check
        if hasattr(request.user, 'midwife_profile') and request.user.midwife_profile != consultation.midwife and not request.user.is_staff:
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

        # Update linked appointment status to COMPLETED
        if consultation.appointment:
            consultation.appointment.status = Appointment.AppointmentStatus.COMPLETED
            consultation.appointment.save(update_fields=['status'])

        # End any active voice or video session
        if hasattr(consultation, 'voice_session'):
            consultation.voice_session.status = VoiceSession.VoiceSessionStatus.ENDED
            consultation.voice_session.ended_at = timezone.now()
            consultation.voice_session.save()

        if hasattr(consultation, 'video_session'):
            consultation.video_session.status = VideoSession.VideoSessionStatus.ENDED
            consultation.video_session.ended_at = timezone.now()
            consultation.video_session.save()

        # Notify user
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
        consultation = self.get_object()

        # Rule 3: Only assigned midwife can add notes
        if not hasattr(request.user, 'midwife_profile') or request.user.midwife_profile != consultation.midwife:
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

    @extend_schema(summary="Manage Virtual Voice Session status", tags=["Consultations"])
    @action(detail=True, methods=['post'], url_path='voice-session')
    def manage_voice_session(self, request, pk=None):
        consultation = self.get_object()
        action_type = request.data.get('action', 'STATUS')  # START, END, GET

        session, _ = VoiceSession.objects.get_or_create(
            consultation=consultation,
            defaults={"session_key": f"VOICE-{uuid.uuid4().hex[:12].upper()}", "status": VoiceSession.VoiceSessionStatus.INITIATED}
        )

        if action_type == 'START':
            session.status = VoiceSession.VoiceSessionStatus.ONGOING
            session.started_at = timezone.now()
            session.save()
        elif action_type == 'END':
            session.status = VoiceSession.VoiceSessionStatus.ENDED
            session.ended_at = timezone.now()
            session.save()

        serializer = VoiceSessionSerializer(session)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @extend_schema(summary="Manage Virtual Video Session status", tags=["Consultations"])
    @action(detail=True, methods=['post'], url_path='video-session')
    def manage_video_session(self, request, pk=None):
        consultation = self.get_object()
        action_type = request.data.get('action', 'STATUS')  # START, END, GET

        session, _ = VideoSession.objects.get_or_create(
            consultation=consultation,
            defaults={"session_key": f"VIDEO-{uuid.uuid4().hex[:12].upper()}", "status": VideoSession.VideoSessionStatus.INITIATED}
        )

        if action_type == 'START':
            session.status = VideoSession.VideoSessionStatus.ONGOING
            session.started_at = timezone.now()
            session.save()
        elif action_type == 'END':
            session.status = VideoSession.VideoSessionStatus.ENDED
            session.ended_at = timezone.now()
            session.save()

        serializer = VideoSessionSerializer(session)
        return Response(serializer.data, status=status.HTTP_200_OK)

