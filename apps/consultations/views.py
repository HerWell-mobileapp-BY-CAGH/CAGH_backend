import uuid
import logging
from datetime import timedelta
from django.db import models, transaction
from django.utils import timezone
from django.conf import settings
from rest_framework import viewsets, permissions, status, serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiResponse, inline_serializer

from .models import Consultation, ConsultationNote, VoiceSession
from .serializers import (
    ConsultationSerializer,
    ConsultationNoteSerializer,
    VoiceSessionSerializer,
)
from .services import VoiceCallService
from apps.appointments.models import Appointment
from apps.notifications.models import Notification


logger = logging.getLogger(__name__)


RINGING_TIMEOUT_SECONDS = getattr(settings, 'VOICE_CALL_RINGING_TIMEOUT_SECONDS', 45)


VoiceStartResponseSerializer = inline_serializer(
    name='VoiceStartResponse',
    fields={
        'status': serializers.CharField(default='RINGING'),
        'started_at': serializers.DateTimeField(allow_null=True),
        'call_type': serializers.CharField(default='VOICE'),
        'session_key': serializers.CharField(),
        'call_id': serializers.CharField(),
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
        'call_id': serializers.CharField(),
        'started_at': serializers.DateTimeField(),
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
    Consultation Management ViewSet.
    Handles consultation state transitions, access controls, and voice session lifecycles.
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
            'retrieve', 'add_note', 'start', 'complete', 'manage_voice_session',
            'destroy', 'voice_session_accept', 'voice_session_connect', 'voice_session_decline',
            'voice_session_cancel', 'voice_session_missed', 'voice_session_end',
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

    def _get_display_name(self, u):
        if not u:
            return ""
        if hasattr(u, 'profile') and u.profile:
            fn = getattr(u.profile, 'first_name', '').strip()
            ln = getattr(u.profile, 'last_name', '').strip()
            if fn or ln:
                return f"{fn} {ln}".strip()
        if hasattr(u, 'first_name') and (getattr(u, 'first_name', '') or getattr(u, 'last_name', '')):
            fn = getattr(u, 'first_name', '').strip()
            ln = getattr(u, 'last_name', '').strip()
            if fn or ln:
                return f"{fn} {ln}".strip()
        return getattr(u, 'username', '')

    def _check_and_auto_expire_ringing_session(self, session):
        """
        Backend safety check: Auto-expires a ringing call if no response within RINGING_TIMEOUT_SECONDS.
        """
        if session and session.status == VoiceSession.VoiceSessionStatus.RINGING:
            reference_time = getattr(session, 'updated_at', None) or session.started_at or session.consultation.updated_at
            if reference_time and (timezone.now() - reference_time) > timedelta(seconds=RINGING_TIMEOUT_SECONDS):
                session.status = VoiceSession.VoiceSessionStatus.MISSED
                session.ended_at = timezone.now()
                session.save(update_fields=['status', 'ended_at'])

    def _broadcast_call_status(self, consultation, session, user, action_type, ended_at=None):
        """
        Broadcasts call signaling status changes via Django Channels WebSockets to both consultation and target user channels.
        """
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            if not channel_layer:
                return

            action_lower = action_type.lower()
            event_type = f"broadcast_call_{action_lower}"
            event_name = f"call_{action_lower}"

            ws_payload = {
                'type': event_type,
                'action': event_name,
                'event': event_name,
                'status': action_type,
                'sender_id': str(user.id),
                'consultation_id': str(consultation.id),
            }
            if ended_at:
                ws_payload['ended_at'] = ended_at.isoformat() if hasattr(ended_at, 'isoformat') else ended_at

            async_to_sync(channel_layer.group_send)(
                f"consultation_call_{consultation.id}",
                ws_payload
            )

            recipient_id = None
            if session and session.caller and str(session.caller.id) != str(user.id):
                recipient_id = session.caller.id
            else:
                if consultation.user_id != user.id:
                    recipient_id = consultation.user_id
                elif consultation.midwife and hasattr(consultation.midwife, 'user') and consultation.midwife.user:
                    recipient_id = consultation.midwife.user.id

            if recipient_id:
                signal_data = dict(ws_payload)
                signal_data['type'] = 'call_signal'
                signal_data['action'] = event_name
                signal_data['event'] = event_name
                signal_data['data'] = ws_payload
                async_to_sync(channel_layer.group_send)(
                    f"user_calls_{recipient_id}",
                    signal_data
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"Error broadcasting call status ({action_type}): {e}")

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
        consultation = self.get_object()
        res_data = VoiceCallService.start_call(consultation, request.user, call_type="VOICE")
        res_data['consultation'] = self.get_serializer(consultation).data
        return Response(res_data, status=status.HTTP_200_OK)

    def _get_voice_session(self, consultation, select_for_update=False):
        return VoiceCallService.get_voice_session(consultation, select_for_update=select_for_update)

    @extend_schema(
        summary="Start consultation call ringing (Voice Session Alias)",
        tags=["Consultations"],
        responses={200: VoiceStartResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/start')
    def voice_session_start(self, request, pk=None):
        return self.start(request, pk=pk)

    def _execute_voice_action_logging(self, request, pk, action_name, service_method):
        user = getattr(request, 'user', None)
        user_id_str = str(getattr(user, 'id', 'anonymous'))
        req_id = f"{action_name[:4].upper()}-{uuid.uuid4().hex[:6].upper()}"
        client_source = 'HTTP'
        if isinstance(request.data, dict):
            client_source = request.data.get('source') or request.data.get('client_source') or 'HTTP'

        logger.info(
            f"[CALL-ACTION] request_id={req_id} source={client_source} action={action_name} event=REQUEST_RECEIVED consultation_id={pk} user_id={user_id_str}"
        )

        if not user or not user.is_authenticated:
            logger.warning(
                f"[CALL-ACTION] request_id={req_id} source={client_source} action={action_name} event=AUTH_FAILURE consultation_id={pk} user_id={user_id_str} status=401"
            )
            return Response({"detail": "Authentication credentials were not provided."}, status=status.HTTP_401_UNAUTHORIZED)

        logger.info(
            f"[CALL-ACTION] request_id={req_id} source={client_source} action={action_name} event=PROCESSING_STARTED consultation_id={pk} user_id={user_id_str}"
        )

        try:
            consultation = self.get_object()
        except PermissionDenied as pd:
            logger.warning(
                f"[CALL-ACTION] request_id={req_id} source={client_source} action={action_name} event=AUTH_FAILURE consultation_id={pk} user_id={user_id_str} status=403 reason=permission_denied"
            )
            raise
        except Exception as ex:
            logger.error(
                f"[CALL-ACTION] request_id={req_id} source={client_source} action={action_name} event=ERROR consultation_id={pk} user_id={user_id_str} error_type={type(ex).__name__}"
            )
            raise

        try:
            data, code = service_method(consultation, user)
            if code in [200, 201]:
                logger.info(
                    f"[CALL-ACTION] request_id={req_id} source={client_source} action={action_name} event=SUCCESS consultation_id={pk} user_id={user_id_str} status={code}"
                )
            elif code == 409:
                reason = "invalid_state"
                if isinstance(data, dict):
                    err_msg = data.get("error", "")
                    if "status is" in err_msg:
                        reason = err_msg.split("status is")[-1].strip().replace("'", "").replace(".", "")
                    elif err_msg:
                        reason = err_msg
                logger.warning(
                    f"[CALL-ACTION] request_id={req_id} source={client_source} action={action_name} event=CONFLICT consultation_id={pk} user_id={user_id_str} status=409 reason={reason}"
                )
            else:
                reason = data.get("error", "rejected") if isinstance(data, dict) else "rejected"
                logger.warning(
                    f"[CALL-ACTION] request_id={req_id} source={client_source} action={action_name} event=REJECTED consultation_id={pk} user_id={user_id_str} status={code} reason={reason}"
                )
            return Response(data, status=code)
        except PermissionDenied as pd:
            logger.warning(
                f"[CALL-ACTION] request_id={req_id} source={client_source} action={action_name} event=AUTH_FAILURE consultation_id={pk} user_id={user_id_str} status=403 reason=permission_denied"
            )
            raise
        except Exception as ex:
            logger.error(
                f"[CALL-ACTION] request_id={req_id} source={client_source} action={action_name} event=ERROR consultation_id={pk} user_id={user_id_str} error_type={type(ex).__name__}"
            )
            raise

    @extend_schema(
        summary="Accept Voice Call",
        tags=["Consultations"],
        responses={200: VoiceAcceptResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/accept')
    def voice_session_accept(self, request, pk=None):
        return self._execute_voice_action_logging(request, pk, 'ACCEPT', VoiceCallService.accept_call)

    @extend_schema(
        summary="Mark Call ONGOING when Voice Session Connects",
        tags=["Consultations"],
        responses={200: VoiceStatusResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/connect')
    def voice_session_connect(self, request, pk=None):
        consultation = self.get_object()
        data, code = VoiceCallService.connect_call(consultation, request.user)
        return Response(data, status=code)

    @extend_schema(
        summary="Decline Voice Call",
        tags=["Consultations"],
        responses={200: VoiceStatusResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/decline')
    def voice_session_decline(self, request, pk=None):
        return self._execute_voice_action_logging(request, pk, 'DECLINE', VoiceCallService.decline_call)

    @extend_schema(
        summary="Cancel Voice Call (Caller side)",
        tags=["Consultations"],
        responses={200: VoiceStatusResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/cancel')
    def voice_session_cancel(self, request, pk=None):
        return self._execute_voice_action_logging(request, pk, 'CANCEL', VoiceCallService.cancel_call)

    @extend_schema(
        summary="Mark Voice Call as Missed (Ringing Timeout)",
        tags=["Consultations"],
        responses={200: VoiceStatusResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/missed')
    def voice_session_missed(self, request, pk=None):
        consultation = self.get_object()
        data, code = VoiceCallService.missed_call(consultation, request.user)
        return Response(data, status=code)

    @extend_schema(
        summary="End Voice Call",
        tags=["Consultations"],
        responses={200: VoiceStatusResponseSerializer}
    )
    @action(detail=True, methods=['post'], url_path='voice-session/end')
    def voice_session_end(self, request, pk=None):
        return self._execute_voice_action_logging(request, pk, 'END', VoiceCallService.end_call)

    @extend_schema(summary="Manage Virtual Voice Session status", tags=["Consultations"])
    @action(detail=True, methods=['get', 'post'], url_path='voice-session')
    def manage_voice_session(self, request, pk=None):
        action_type = request.data.get('action', 'STATUS') if request.method == 'POST' else 'STATUS'

        if action_type == 'START':
            return self.start(request, pk=pk)
        elif action_type == 'ACCEPT':
            return self.voice_session_accept(request, pk=pk)
        elif action_type == 'CONNECT':
            consultation = self.get_object()
            data, code = VoiceCallService.connect_call(consultation, request.user)
            return Response(data, status=code)
        elif action_type == 'DECLINE':
            return self.voice_session_decline(request, pk=pk)
        elif action_type == 'CANCEL':
            return self.voice_session_cancel(request, pk=pk)
        elif action_type == 'MISSED':
            consultation = self.get_object()
            data, code = VoiceCallService.missed_call(consultation, request.user)
            return Response(data, status=code)
        else:
            consultation = self.get_object()
            session = self._get_voice_session(consultation)
            return Response({
                'consultation_id': str(consultation.id),
                'status': session.status if session else 'NONE',
                'session_key': session.session_key if session else None,
            }, status=status.HTTP_200_OK)

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
