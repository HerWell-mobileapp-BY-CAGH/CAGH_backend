import uuid
from datetime import timedelta
from django.db import models, transaction
from django.utils import timezone
from django.conf import settings
from rest_framework import viewsets, permissions, status, serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer

from .models import Consultation, ConsultationNote, VoiceSession, VideoSession
from .serializers import (
    ConsultationSerializer,
    ConsultationNoteSerializer,
    VoiceSessionSerializer,
    VideoSessionSerializer,
)
from .agora_service import AgoraService, Role as AgoraRole
from apps.appointments.models import Appointment
from apps.notifications.models import Notification
from apps.notifications.call_notifications import send_incoming_call_notification


RINGING_TIMEOUT_SECONDS = getattr(settings, 'VOICE_CALL_RINGING_TIMEOUT_SECONDS', 45)


VoiceStartResponseSerializer = inline_serializer(
    name='VoiceStartResponse',
    fields={
        'status': serializers.CharField(default='RINGING'),
        'started_at': serializers.DateTimeField(allow_null=True),
        'call_type': serializers.CharField(default='VOICE'),
        'session_key': serializers.CharField(),
        'agora_channel_name': serializers.CharField(),
        'agora_app_id': serializers.CharField(),
        'caller_id': serializers.CharField(),
        'recipient_id': serializers.CharField(),
        'recipient_name': serializers.CharField(),
        'consultation': ConsultationSerializer(),
    }
)

VoiceAcceptResponseSerializer = inline_serializer(
    name='VoiceAcceptResponse',
    fields={
        'status': serializers.CharField(default='ACCEPTED'),
        'session_key': serializers.CharField(),
        'agora_channel_name': serializers.CharField(),
        'agora_app_id': serializers.CharField(),
        'agora_token': serializers.CharField(),
        'uid': serializers.IntegerField(),
        'started_at': serializers.DateTimeField(),
    }
)

VoiceTokenResponseSerializer = inline_serializer(
    name='VoiceTokenResponse',
    fields={
        'agora_app_id': serializers.CharField(),
        'agora_channel_name': serializers.CharField(),
        'agora_token': serializers.CharField(),
        'uid': serializers.IntegerField(),
        'session_key': serializers.CharField(),
        'status': serializers.CharField(),
    }
)

VoiceStatusResponseSerializer = inline_serializer(
    name='VoiceStatusResponse',
    fields={
        'status': serializers.CharField(),
        'ended_at': serializers.DateTimeField(allow_null=True),
    }
)


class ConsultationViewSet(viewsets.ModelViewSet):
    """
    Module 4 — Consultation Management
    Enforces all SRS business rules, atomic state transitions, strict authorization, and Agora voice session lifecycle.
    """

    queryset = Consultation.objects.all().select_related('appointment', 'user', 'midwife', 'midwife__user').prefetch_related('notes')
    serializer_class = ConsultationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = Consultation.objects.all().select_related('appointment', 'user', 'midwife', 'midwife__user').prefetch_related('notes')

        if self.action in [
            'retrieve', 'add_note', 'start', 'complete', 'manage_voice_session', 'manage_video_session',
            'destroy', 'voice_session_accept', 'voice_session_connect', 'voice_session_decline',
            'voice_session_cancel', 'voice_session_missed', 'voice_session_end', 'voice_session_token'
        ]:
            return queryset

        if user.is_staff or getattr(user, 'role', '') == 'ADMIN':
            return queryset

        if hasattr(user, 'midwife_profile'):
            return queryset.filter(models.Q(user=user) | models.Q(midwife=user.midwife_profile))

        return queryset.filter(user=user)

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
        Enforces strict participant authorization across all call operations.
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
            raise PermissionDenied("You are not authorized to participate in this consultation call.")

        return consultation, is_patient, is_midwife

    def _check_and_auto_expire_ringing_session(self, session):
        """
        Backend safety check: Auto-expires a ringing call if no response within RINGING_TIMEOUT_SECONDS.
        """
        if session and session.status == VoiceSession.VoiceSessionStatus.RINGING:
            reference_time = session.started_at or session.consultation.updated_at
            if reference_time and (timezone.now() - reference_time) > timedelta(seconds=RINGING_TIMEOUT_SECONDS):
                session.status = VoiceSession.VoiceSessionStatus.MISSED
                session.ended_at = timezone.now()
                session.save(update_fields=['status', 'ended_at'])

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

    @extend_schema(
        summary="Start consultation call ringing & dispatch FCM notification",
        tags=["Consultations"],
        responses={200: VoiceStartResponseSerializer}
    )
    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        with transaction.atomic():
            consultation, is_patient, is_midwife = self._get_consultation_and_verify_participant(request, pk)

            if consultation.status == Consultation.ConsultationStatus.COMPLETED:
                return Response({"error": "Completed consultations cannot be restarted."}, status=status.HTTP_400_BAD_REQUEST)

            consultation.status = Consultation.ConsultationStatus.ACTIVE
            consultation.save(update_fields=['status'])

            caller = request.user
            recipient = consultation.user if is_midwife else (consultation.midwife.user if consultation.midwife else None)

            session_key = None
            agora_channel_name = None
            call_type = "VOICE"

            if consultation.consultation_type in (Consultation.ConsultationType.VIRTUAL_VOICE, 'VIRTUAL_VOICE'):
                session = VoiceSession.objects.select_for_update().filter(consultation=consultation).first()
                if not session:
                    session_key = f"VOICE-{uuid.uuid4().hex[:12].upper()}"
                    session = VoiceSession.objects.create(
                        consultation=consultation,
                        session_key=session_key,
                        agora_channel_name=f"cagh_voice_{session_key}",
                        status=VoiceSession.VoiceSessionStatus.RINGING,
                        caller=caller,
                    )
                else:
                    session.status = VoiceSession.VoiceSessionStatus.RINGING
                    session.caller = caller
                    session.ended_at = None
                    if not session.agora_channel_name:
                        session.agora_channel_name = f"cagh_voice_{session.session_key}"
                    session.save()

                session_key = session.session_key
                agora_channel_name = session.agora_channel_name
                call_type = "VOICE"

            elif consultation.consultation_type in (Consultation.ConsultationType.VIRTUAL_VIDEO, 'VIRTUAL_VIDEO'):
                session, _ = VideoSession.objects.select_for_update().get_or_create(
                    consultation=consultation,
                    defaults={"session_key": f"VIDEO-{uuid.uuid4().hex[:12].upper()}", "status": VideoSession.VideoSessionStatus.INITIATED}
                )
                session_key = session.session_key
                agora_channel_name = f"cagh_video_{session_key}"
                call_type = "VIDEO"

        # FCM Call Notification (Graceful fallback if FCM token missing or push fails)
        try:
            send_incoming_call_notification(caller=caller, recipient=recipient, consultation=consultation, call_type=call_type, session_key=session_key)
        except Exception:
            pass

        agora_app_id = getattr(settings, 'AGORA_APP_ID', 'cagh_agora_app_id_placeholder')
        serializer = self.get_serializer(consultation)

        return Response({
            'status': 'RINGING',
            'started_at': consultation.started_at,
            'call_type': call_type,
            'session_key': session_key,
            'agora_channel_name': agora_channel_name,
            'agora_app_id': agora_app_id,
            'caller_id': str(caller.id),
            'recipient_id': str(recipient.id) if recipient else "",
            'recipient_name': getattr(recipient, 'username', 'Midwife'),
            'consultation': serializer.data,
        }, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Start consultation call ringing (Voice Session Alias)",
        tags=["Consultations"],
        responses={200: VoiceStartResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/start')
    def voice_session_start(self, request, pk=None):
        return self.start(request, pk=pk)

    @extend_schema(
        summary="Accept Voice Call & Retrieve Signed Agora Token",

        tags=["Consultations"],
        responses={200: VoiceAcceptResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/accept')
    def voice_session_accept(self, request, pk=None):
        with transaction.atomic():
            consultation, is_patient, is_midwife = self._get_consultation_and_verify_participant(request, pk)

            session = VoiceSession.objects.select_for_update().filter(consultation=consultation).first()
            if not session:
                return Response({"error": "No voice session found to accept."}, status=status.HTTP_404_NOT_FOUND)

            # Auto-expire check
            self._check_and_auto_expire_ringing_session(session)

            # Race condition protection: Reject if already cancelled, declined, missed, or ended
            if session.status in [VoiceSession.VoiceSessionStatus.CANCELLED, VoiceSession.VoiceSessionStatus.DECLINED, VoiceSession.VoiceSessionStatus.MISSED, VoiceSession.VoiceSessionStatus.ENDED]:
                return Response(
                    {"error": f"Cannot accept call. Call status is '{session.status}'."},
                    status=status.HTTP_409_CONFLICT
                )

            session.status = VoiceSession.VoiceSessionStatus.ACCEPTED
            if not session.started_at:
                session.started_at = timezone.now()
            if not session.agora_channel_name:
                session.agora_channel_name = f"cagh_voice_{session.session_key}"
            session.save()

            consultation.status = Consultation.ConsultationStatus.ACTIVE
            if not consultation.started_at:
                consultation.started_at = timezone.now()
            consultation.save()

        agora_app_id = getattr(settings, 'AGORA_APP_ID', 'cagh_agora_app_id_placeholder')
        token = AgoraService.generate_rtc_token(
            channel_name=session.agora_channel_name,
            uid=request.user.id,
            role=AgoraRole.PUBLISHER
        )

        return Response({
            'status': 'ACCEPTED',
            'session_key': session.session_key,
            'agora_channel_name': session.agora_channel_name,
            'agora_app_id': agora_app_id,
            'agora_token': token,
            'uid': request.user.id,
            'started_at': session.started_at,
        }, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Mark Call ONGOING when Agora Audio Connects",
        tags=["Consultations"],
        responses={200: VoiceStatusResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/connect')
    def voice_session_connect(self, request, pk=None):
        with transaction.atomic():
            consultation, is_patient, is_midwife = self._get_consultation_and_verify_participant(request, pk)
            session = VoiceSession.objects.select_for_update().filter(consultation=consultation).first()
            if not session:
                return Response({"error": "No voice session found."}, status=status.HTTP_404_NOT_FOUND)

            if session.status in [VoiceSession.VoiceSessionStatus.ACCEPTED, VoiceSession.VoiceSessionStatus.RINGING]:
                session.status = VoiceSession.VoiceSessionStatus.ONGOING
                session.save(update_fields=['status'])

        return Response({'status': session.status}, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Decline Voice Call",
        tags=["Consultations"],
        responses={200: VoiceStatusResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/decline')
    def voice_session_decline(self, request, pk=None):
        with transaction.atomic():
            consultation, is_patient, is_midwife = self._get_consultation_and_verify_participant(request, pk)
            session = VoiceSession.objects.select_for_update().filter(consultation=consultation).first()
            if not session:
                return Response({"error": "No voice session found."}, status=status.HTTP_404_NOT_FOUND)

            if session.status == VoiceSession.VoiceSessionStatus.DECLINED:
                return Response({'status': 'DECLINED', 'ended_at': session.ended_at}, status=status.HTTP_200_OK)

            if session.status not in [VoiceSession.VoiceSessionStatus.RINGING, VoiceSession.VoiceSessionStatus.INITIATED]:
                return Response(
                    {"error": f"Cannot decline call. Call status is '{session.status}'."},
                    status=status.HTTP_409_CONFLICT
                )

            session.status = VoiceSession.VoiceSessionStatus.DECLINED
            session.ended_at = timezone.now()
            session.save()

        return Response({'status': 'DECLINED', 'ended_at': session.ended_at}, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Cancel Voice Call (Caller side)",
        tags=["Consultations"],
        responses={200: VoiceStatusResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/cancel')
    def voice_session_cancel(self, request, pk=None):
        with transaction.atomic():
            consultation, is_patient, is_midwife = self._get_consultation_and_verify_participant(request, pk)
            session = VoiceSession.objects.select_for_update().filter(consultation=consultation).first()
            if not session:
                return Response({"error": "No voice session found."}, status=status.HTTP_404_NOT_FOUND)

            if session.status == VoiceSession.VoiceSessionStatus.CANCELLED:
                return Response({'status': 'CANCELLED', 'ended_at': session.ended_at}, status=status.HTTP_200_OK)

            if session.status not in [VoiceSession.VoiceSessionStatus.RINGING, VoiceSession.VoiceSessionStatus.INITIATED]:
                return Response(
                    {"error": f"Cannot cancel call. Call status is '{session.status}'."},
                    status=status.HTTP_409_CONFLICT
                )

            session.status = VoiceSession.VoiceSessionStatus.CANCELLED
            session.ended_at = timezone.now()
            session.save()

        return Response({'status': 'CANCELLED', 'ended_at': session.ended_at}, status=status.HTTP_200_OK)

    @extend_schema(
        summary="Mark Voice Call as Missed (Ringing Timeout)",
        tags=["Consultations"],
        responses={200: VoiceStatusResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/missed')
    def voice_session_missed(self, request, pk=None):
        with transaction.atomic():
            consultation, is_patient, is_midwife = self._get_consultation_and_verify_participant(request, pk)
            session = VoiceSession.objects.select_for_update().filter(consultation=consultation).first()
            if not session:
                return Response({"error": "No voice session found."}, status=status.HTTP_404_NOT_FOUND)

            if session.status == VoiceSession.VoiceSessionStatus.MISSED:
                return Response({'status': 'MISSED', 'ended_at': session.ended_at}, status=status.HTTP_200_OK)

            session.status = VoiceSession.VoiceSessionStatus.MISSED
            session.ended_at = timezone.now()
            session.save()

        return Response({'status': 'MISSED', 'ended_at': session.ended_at}, status=status.HTTP_200_OK)

    @extend_schema(
        summary="End Voice Call",
        tags=["Consultations"],
        responses={200: VoiceStatusResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/end')
    def voice_session_end(self, request, pk=None):
        with transaction.atomic():
            consultation, is_patient, is_midwife = self._get_consultation_and_verify_participant(request, pk)
            session = VoiceSession.objects.select_for_update().filter(consultation=consultation).first()
            if not session:
                return Response({"error": "No voice session found."}, status=status.HTTP_404_NOT_FOUND)

            if session.status in [VoiceSession.VoiceSessionStatus.ENDED, VoiceSession.VoiceSessionStatus.CANCELLED, VoiceSession.VoiceSessionStatus.DECLINED, VoiceSession.VoiceSessionStatus.MISSED, VoiceSession.VoiceSessionStatus.FAILED]:
                return Response({'status': session.status, 'ended_at': session.ended_at}, status=status.HTTP_200_OK)

            session.status = VoiceSession.VoiceSessionStatus.ENDED
            session.ended_at = timezone.now()
            session.save()

        return Response({'status': 'ENDED', 'ended_at': session.ended_at}, status=status.HTTP_200_OK)


    @extend_schema(
        summary="Get authorized short-lived Agora Token for active call",
        tags=["Consultations"],
        responses={200: VoiceTokenResponseSerializer}
    )
    @action(detail=True, methods=['get', 'post'], url_path='voice-session/token')
    def voice_session_token(self, request, pk=None):
        consultation, is_patient, is_midwife = self._get_consultation_and_verify_participant(request, pk)

        if not hasattr(consultation, 'voice_session'):
            return Response({'error': 'No voice session found for this consultation.'}, status=status.HTTP_404_NOT_FOUND)

        session = consultation.voice_session
        self._check_and_auto_expire_ringing_session(session)

        if session.status in [VoiceSession.VoiceSessionStatus.CANCELLED, VoiceSession.VoiceSessionStatus.DECLINED, VoiceSession.VoiceSessionStatus.MISSED, VoiceSession.VoiceSessionStatus.ENDED, VoiceSession.VoiceSessionStatus.FAILED]:
            return Response({'error': f"Cannot issue token. Voice session is in '{session.status}' state."}, status=status.HTTP_400_BAD_REQUEST)

        if not session.agora_channel_name:
            session.agora_channel_name = f"cagh_voice_{session.session_key}"
            session.save(update_fields=['agora_channel_name'])

        agora_app_id = getattr(settings, 'AGORA_APP_ID', 'cagh_agora_app_id_placeholder')
        token = AgoraService.generate_rtc_token(
            channel_name=session.agora_channel_name,
            uid=request.user.id,
            role=AgoraRole.PUBLISHER
        )

        return Response({
            'agora_app_id': agora_app_id,
            'agora_channel_name': session.agora_channel_name,
            'agora_token': token,
            'uid': request.user.id,
            'session_key': session.session_key,
            'status': session.status,
        }, status=status.HTTP_200_OK)

    @extend_schema(summary="Manage Virtual Voice Session status", tags=["Consultations"])
    @action(detail=True, methods=['get', 'post'], url_path='voice-session')
    def manage_voice_session(self, request, pk=None):
        consultation, is_patient, is_midwife = self._get_consultation_and_verify_participant(request, pk)
        action_type = request.data.get('action', 'STATUS') if request.method == 'POST' else 'STATUS'

        with transaction.atomic():
            session = VoiceSession.objects.select_for_update().filter(consultation=consultation).first()
            if not session:
                session_key = f"VOICE-{uuid.uuid4().hex[:12].upper()}"
                session = VoiceSession.objects.create(
                    consultation=consultation,
                    session_key=session_key,
                    agora_channel_name=f"cagh_voice_{session_key}",
                    status=VoiceSession.VoiceSessionStatus.INITIATED,
                    caller=request.user,
                )

            self._check_and_auto_expire_ringing_session(session)

            if action_type == 'START':
                session.status = VoiceSession.VoiceSessionStatus.RINGING
                session.caller = request.user
                session.save()
            elif action_type == 'ACCEPT':
                session.status = VoiceSession.VoiceSessionStatus.ACCEPTED
                if not session.started_at:
                    session.started_at = timezone.now()
                session.save()
            elif action_type == 'CONNECT':
                session.status = VoiceSession.VoiceSessionStatus.ONGOING
                session.save()
            elif action_type == 'DECLINE':
                session.status = VoiceSession.VoiceSessionStatus.DECLINED
                session.ended_at = timezone.now()
                session.save()
            elif action_type == 'CANCEL':
                session.status = VoiceSession.VoiceSessionStatus.CANCELLED
                session.ended_at = timezone.now()
                session.save()
            elif action_type == 'MISSED':
                session.status = VoiceSession.VoiceSessionStatus.MISSED
                session.ended_at = timezone.now()
                session.save()
            elif action_type == 'END':
                session.status = VoiceSession.VoiceSessionStatus.ENDED
                session.ended_at = timezone.now()
                session.save()

        agora_app_id = getattr(settings, 'AGORA_APP_ID', 'cagh_agora_app_id_placeholder')
        agora_token = AgoraService.generate_rtc_token(
            channel_name=session.agora_channel_name,
            uid=request.user.id,
            role=AgoraRole.PUBLISHER
        )

        serializer = VoiceSessionSerializer(session)
        data = serializer.data
        data['agora_app_id'] = agora_app_id
        data['agora_token'] = agora_token
        data['uid'] = request.user.id
        return Response(data, status=status.HTTP_200_OK)

    @extend_schema(summary="Manage Virtual Video Session status", tags=["Consultations"])
    @action(detail=True, methods=['post'], url_path='video-session')
    def manage_video_session(self, request, pk=None):
        consultation, is_patient, is_midwife = self._get_consultation_and_verify_participant(request, pk)
        action_type = request.data.get('action', 'STATUS')

        session, _ = VideoSession.objects.get_or_create(
            consultation=consultation,
            defaults={"session_key": f"VIDEO-{uuid.uuid4().hex[:12].upper()}", "status": VideoSession.VideoSessionStatus.INITIATED}
        )

        if action_type == 'START':
            session.status = 'ONGOING'
            session.started_at = timezone.now()
            session.save()
        elif action_type == 'END':
            session.status = 'ENDED'
            session.ended_at = timezone.now()
            session.save()

        serializer = VideoSessionSerializer(session)
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

        if hasattr(consultation, 'voice_session'):
            consultation.voice_session.status = VoiceSession.VoiceSessionStatus.ENDED
            consultation.voice_session.ended_at = timezone.now()
            consultation.voice_session.save()

        if hasattr(consultation, 'video_session'):
            consultation.video_session.status = VideoSession.VideoSessionStatus.ENDED
            consultation.video_session.ended_at = timezone.now()
            consultation.video_session.save()

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
