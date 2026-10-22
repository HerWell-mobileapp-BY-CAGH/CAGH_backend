import logging
logger = logging.getLogger(__name__)
from datetime import datetime, timedelta
from django.db import models
from django.utils import timezone
from rest_framework import viewsets, permissions, status, exceptions
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import Availability, TimeSlot, Appointment
from .serializers import AvailabilitySerializer, TimeSlotSerializer, AppointmentSerializer
from apps.midwives.models import MidwifeProfile
from apps.notifications.models import Notification
from apps.notifications.push_notifications import send_general_push_notification


def _format_appointment_info(appointment):
    raw_type = appointment.appointment_type
    if raw_type == 'IN_PERSON':
        type_str = "In-Person"
    elif raw_type == 'VIRTUAL_VOICE':
        type_str = "Voice Call"
    elif raw_type == 'VIRTUAL_VIDEO':
        type_str = "Video Call"
    else:
        type_str = appointment.get_appointment_type_display()

    today = timezone.localdate()
    apt_date = appointment.scheduled_date
    if apt_date == today:
        date_str = "Today"
    elif apt_date == today + timedelta(days=1):
        date_str = "Tomorrow"
    else:
        date_str = apt_date.strftime("%a, %b %d")

    time_str = appointment.start_time.strftime("%I:%M %p").lstrip('0') if appointment.start_time else ""

    patient_name = appointment.user.get_full_name() or appointment.user.username
    if appointment.midwife and appointment.midwife.user:
        midwife_name = appointment.midwife.user.get_full_name() or appointment.midwife.user.username
    else:
        midwife_name = "Midwife"

    return type_str, date_str, time_str, patient_name, midwife_name


def _notify_user_and_midwife(appointment, action_type="APPOINTMENT_UPDATE"):
    """
    Sends clear, user-friendly in-app and FCM push notifications tailored for Patient and Midwife.
    """
    type_str, date_str, time_str, patient_name, midwife_name = _format_appointment_info(appointment)

    if action_type in ["APPOINTMENT_BOOKED", "APPOINTMENT_SCHEDULED"]:
        title_pat = "Appointment Scheduled 🎉"
        body_pat = f"Your {type_str} consultation with Midwife {midwife_name} is scheduled for {date_str} at {time_str}."
        title_mw = "New Booking Request 📅"
        body_mw = f"New {type_str} booking from {patient_name} for {date_str} at {time_str}."
    elif action_type == "APPOINTMENT_CONFIRMED":
        title_pat = "Appointment Confirmed ✅"
        body_pat = f"Midwife {midwife_name} confirmed your {type_str} consultation for {date_str} at {time_str}."
        title_mw = "Appointment Confirmed ✅"
        body_mw = f"You confirmed the {type_str} consultation with {patient_name} for {date_str} at {time_str}."
    elif action_type == "APPOINTMENT_CANCELLED":
        title_pat = "Appointment Cancelled"
        body_pat = f"Your {type_str} consultation with Midwife {midwife_name} on {date_str} at {time_str} was cancelled."
        title_mw = "Appointment Cancelled"
        body_mw = f"The {type_str} appointment with {patient_name} on {date_str} at {time_str} was cancelled."
    elif action_type == "APPOINTMENT_RESCHEDULED":
        title_pat = "Appointment Rescheduled 📅"
        body_pat = f"Your {type_str} consultation with Midwife {midwife_name} was rescheduled to {date_str} at {time_str}."
        title_mw = "Appointment Rescheduled 📅"
        body_mw = f"The {type_str} consultation with {patient_name} was rescheduled to {date_str} at {time_str}."
    elif action_type == "APPOINTMENT_COMPLETED":
        title_pat = "Consultation Completed"
        body_pat = f"Your {type_str} consultation with Midwife {midwife_name} is complete. Thank you!"
        title_mw = "Consultation Completed"
        body_mw = f"You marked the {type_str} consultation with {patient_name} as completed."
    else:
        title_pat = "Appointment Update"
        body_pat = f"Your appointment with Midwife {midwife_name} on {date_str} at {time_str} has been updated."
        title_mw = "Appointment Update"
        body_mw = f"Appointment with {patient_name} on {date_str} at {time_str} has been updated."

    # Patient Notification
    try:
        if appointment.user:
            Notification.objects.create(
                user=appointment.user,
                title=title_pat,
                body=body_pat,
                type="APPOINTMENT",
                action=action_type,
                reference_id=str(appointment.id),
            )
            send_general_push_notification(
                user=appointment.user,
                title=title_pat,
                body=body_pat,
                extra_data={"type": "APPOINTMENT", "action": action_type, "appointment_id": str(appointment.id)},
            )
    except Exception as e:
        logger.warning(f"Error sending patient notification for appointment {appointment.id}: {e}")

    # Midwife Notification
    try:
        if appointment.midwife and appointment.midwife.user:
            Notification.objects.create(
                user=appointment.midwife.user,
                title=title_mw,
                body=body_mw,
                type="APPOINTMENT",
                action=action_type,
                reference_id=str(appointment.id),
            )
            send_general_push_notification(
                user=appointment.midwife.user,
                title=title_mw,
                body=body_mw,
                extra_data={"type": "APPOINTMENT", "action": action_type, "appointment_id": str(appointment.id)},
            )
    except Exception as e:
        logger.warning(f"Error sending midwife notification for appointment {appointment.id}: {e}")


class AvailabilityViewSet(viewsets.ModelViewSet):
    """
    Manages midwife date-specific availability schedules.
    """

    queryset = Availability.objects.all()
    serializer_class = AvailabilitySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = Availability.objects.all()

        midwife_id = self.request.query_params.get('midwife_id')
        if midwife_id:
            queryset = queryset.filter(midwife_id=midwife_id)
        elif hasattr(user, 'midwife_profile') and not (user.is_staff or getattr(user, 'role', '') == 'ADMIN'):
            queryset = queryset.filter(midwife=user.midwife_profile)
        else:
            queryset = queryset.filter(is_active=True)

        date_param = self.request.query_params.get('date')
        if date_param:
            queryset = queryset.filter(date=date_param)

        month_param = self.request.query_params.get('month')
        year_param = self.request.query_params.get('year')
        if month_param and year_param:
            queryset = queryset.filter(date__month=month_param, date__year=year_param)

        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date and end_date:
            queryset = queryset.filter(date__range=[start_date, end_date])

        return queryset

    def perform_create(self, serializer):
        user = self.request.user
        if hasattr(user, 'midwife_profile'):
            if user.midwife_profile.verification_status != MidwifeProfile.VerificationStatus.APPROVED and not user.is_staff:
                raise exceptions.PermissionDenied("Your midwife account is awaiting admin verification before you can publish working hours.")
            serializer.save(midwife=user.midwife_profile)
        else:
            raise exceptions.PermissionDenied("Only registered midwives can set working hours availability.")


def _to_ethiopian_time(t):
    """Converts a standard time object to Ethiopian local time string (e.g. 2:00 ጧት, 11:00 ማታ)."""
    h = t.hour
    m = t.minute
    eth_h = (h - 6) % 12
    if eth_h == 0:
        eth_h = 12
    if 6 <= h < 12:
        period = "ጧት"
    elif 12 <= h < 17:
        period = "ቀን"
    elif 17 <= h < 23:
        period = "ማታ"
    else:
        period = "ሌሊት"
    return f"{eth_h}:{m:02d} {period}"


from django.db import transaction, models, connection


class TimeSlotViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Returns available appointment periods for a midwife on a target date.
    Each Availability period represents ONE complete bookable appointment period.
    """

    queryset = TimeSlot.objects.all()
    serializer_class = TimeSlotSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    @extend_schema(summary="Get available appointment slots for a midwife", tags=["Appointments"])
    def list(self, request, *args, **kwargs):
        midwife_id = request.query_params.get('midwife_id')
        date_str = request.query_params.get('date')

        if not midwife_id or not date_str:
            return Response(
                {"error": "Both midwife_id and date parameters (YYYY-MM-DD) are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"error": "Invalid date format. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            midwife = MidwifeProfile.objects.get(id=midwife_id)
        except MidwifeProfile.DoesNotExist:
            return Response(
                {"error": "Midwife profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Check if midwife account is APPROVED
        if midwife.verification_status != MidwifeProfile.VerificationStatus.APPROVED:
            return Response(
                {"available": False, "reason": "Midwife is not currently verified/approved.", "slots": []},
                status=status.HTTP_200_OK,
            )

        # Check if midwife has toggled off live bookings
        if getattr(midwife, 'is_accepting_bookings', True) is False:
            return Response(
                {"available": False, "reason": "Midwife is currently not accepting new bookings.", "slots": []},
                status=status.HTTP_200_OK,
            )

        # Fetch active availability periods for this midwife on this EXACT calendar date
        availabilities = Availability.objects.filter(
            midwife=midwife,
            date=target_date,
            is_active=True
        ).order_by('start_time')

        if not availabilities.exists():
            return Response(
                {
                    "midwife_id": str(midwife.id),
                    "midwife_name": midwife.user.username,
                    "date": date_str,
                    "available": False,
                    "reason": "No availability configured for this specific date.",
                    "available_slots_count": 0,
                    "morning_slots": [],
                    "afternoon_slots": [],
                    "evening_slots": [],
                    "slots": [],
                },
                status=status.HTTP_200_OK,
            )

        # Get existing PENDING and CONFIRMED appointments for midwife on this date
        booked_appointments = Appointment.objects.filter(
            midwife=midwife,
            scheduled_date=target_date,
            status__in=[Appointment.AppointmentStatus.PENDING, Appointment.AppointmentStatus.CONFIRMED],
        )

        generated_slots = []
        for avail in availabilities:
            methods = avail.consultation_methods or ["IN_PERSON", "VIRTUAL_VOICE"]
            slot_start_time = avail.start_time
            slot_end_time = avail.end_time

            duration_mins = int((datetime.combine(target_date, slot_end_time) - datetime.combine(target_date, slot_start_time)).total_seconds() / 60)

            # Check if this entire availability period overlaps with any booked appointment
            is_booked = booked_appointments.filter(
                start_time__lt=slot_end_time,
                end_time__gt=slot_start_time,
            ).exists()

            generated_slots.append({
                "id": str(avail.id),
                "availability_id": str(avail.id),
                "date": date_str,
                "start_time": slot_start_time.strftime("%H:%M"),
                "end_time": slot_end_time.strftime("%H:%M"),
                "start_time_12h": slot_start_time.strftime("%I:%M %p"),
                "end_time_12h": slot_end_time.strftime("%I:%M %p"),
                "start_time_ethiopian": _to_ethiopian_time(slot_start_time),
                "end_time_ethiopian": _to_ethiopian_time(slot_end_time),
                "duration_minutes": duration_mins,
                "consultation_methods": methods,
                "is_available": not is_booked,
            })

        morning_slots = [s for s in generated_slots if 5 <= int(s["start_time"].split(":")[0]) < 12]
        afternoon_slots = [s for s in generated_slots if 12 <= int(s["start_time"].split(":")[0]) < 17]
        evening_slots = [s for s in generated_slots if 17 <= int(s["start_time"].split(":")[0]) < 23]

        return Response({
            "midwife_id": str(midwife.id),
            "midwife_name": midwife.user.username,
            "date": date_str,
            "offered_consultation_types": midwife.offered_consultation_types,
            "available_slots_count": len([s for s in generated_slots if s["is_available"]]),
            "morning_slots": morning_slots,
            "afternoon_slots": afternoon_slots,
            "evening_slots": evening_slots,
            "slots": generated_slots,
        }, status=status.HTTP_200_OK)


class AppointmentViewSet(viewsets.ModelViewSet):
    """
    Handles appointment creation, scheduling, status updates, and notifications.
    """

    queryset = Appointment.objects.all().select_related(
        'user', 'user__profile', 'user__preferences', 'user__midwife_profile',
        'midwife', 'midwife__user', 'midwife__user__profile', 'midwife__user__preferences', 'midwife__user__midwife_profile', 'midwife__hospital', 'created_by'
    )
    serializer_class = AppointmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = Appointment.objects.all().select_related(
            'user', 'user__profile', 'user__preferences', 'user__midwife_profile',
            'midwife', 'midwife__user', 'midwife__user__profile', 'midwife__user__preferences', 'midwife__user__midwife_profile', 'midwife__hospital', 'created_by'
        )

        if user.is_staff or getattr(user, 'role', '') == 'ADMIN':
            return queryset

        if hasattr(user, 'midwife_profile'):
            return queryset.filter(models.Q(user=user) | models.Q(midwife=user.midwife_profile))

        return queryset.filter(user=user)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        midwife = serializer.validated_data.get('midwife')
        scheduled_date = serializer.validated_data.get('scheduled_date')
        start_time = serializer.validated_data.get('start_time')
        end_time = serializer.validated_data.get('end_time')

        # Lock active appointments for this midwife and date to prevent concurrent double-booking
        if midwife and scheduled_date and start_time and end_time:
            query = Appointment.objects.filter(
                midwife=midwife,
                scheduled_date=scheduled_date,
                status__in=[Appointment.AppointmentStatus.PENDING, Appointment.AppointmentStatus.CONFIRMED],
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            if connection.vendor != 'sqlite':
                query = query.select_for_update()

            _locked_existing = list(query)
            if len(_locked_existing) > 0:
                return Response(
                    {"detail": "This time slot is already booked for another appointment. Please choose a different time."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        midwife = serializer.validated_data.get('midwife')
        fee = serializer.validated_data.get('fee')
        if fee is None and midwife and hasattr(midwife, 'consultation_fee'):
            fee = midwife.consultation_fee

        appointment = serializer.save(
            user=self.request.user,
            created_by=self.request.user,
            fee=fee if fee is not None else 0.00
        )

        # Send dual-side notification
        _notify_user_and_midwife(appointment, action_type="APPOINTMENT_BOOKED")

    @extend_schema(summary="Cancel a scheduled appointment", tags=["Appointments"])
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        appointment = self.get_object()
        user = request.user
        if not user.is_staff and getattr(user, 'role', '') != 'ADMIN':
            is_patient = appointment.user == user
            is_assigned_midwife = hasattr(user, 'midwife_profile') and appointment.midwife == user.midwife_profile
            if not (is_patient or is_assigned_midwife):
                return Response({'error': 'You do not have permission to cancel this appointment.'}, status=status.HTTP_403_FORBIDDEN)

        if appointment.status == Appointment.AppointmentStatus.CANCELLED:
            return Response({'message': 'Appointment is already cancelled.'}, status=status.HTTP_200_OK)

        appointment.status = Appointment.AppointmentStatus.CANCELLED
        appointment.save()

        # Notify patient and midwife
        _notify_user_and_midwife(appointment, action_type="APPOINTMENT_CANCELLED")

        return Response({
            'status': 'CANCELLED',
            'message': 'Appointment cancelled successfully.',
            'appointment_number': appointment.appointment_number,
        }, status=status.HTTP_200_OK)

    @extend_schema(summary="Reschedule a scheduled appointment", tags=["Appointments"])
    @action(detail=True, methods=['post'])
    def reschedule(self, request, pk=None):
        appointment = self.get_object()
        user = request.user
        if not user.is_staff and getattr(user, 'role', '') != 'ADMIN':
            is_patient = appointment.user == user
            is_assigned_midwife = hasattr(user, 'midwife_profile') and appointment.midwife == user.midwife_profile
            if not (is_patient or is_assigned_midwife):
                return Response({'error': 'You do not have permission to reschedule this appointment.'}, status=status.HTTP_403_FORBIDDEN)

        new_date = request.data.get('scheduled_date')
        new_start = request.data.get('start_time')
        new_end = request.data.get('end_time')

        if not new_date or not new_start or not new_end:
            return Response(
                {'error': 'scheduled_date, start_time, and end_time are required fields.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = self.get_serializer(
            appointment,
            data={'scheduled_date': new_date, 'start_time': new_start, 'end_time': new_end, 'status': Appointment.AppointmentStatus.PENDING},
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        updated_apt = serializer.save()

        # Notify patient and midwife
        _notify_user_and_midwife(updated_apt, action_type="APPOINTMENT_RESCHEDULED")

        return Response({
            'status': updated_apt.status,
            'message': 'Appointment rescheduled successfully.',
            'appointment': serializer.data,
        }, status=status.HTTP_200_OK)

    @extend_schema(summary="Midwife action: Confirm appointment", tags=["Appointments"])
    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        appointment = self.get_object()
        user = request.user
        if not user.is_staff and getattr(user, 'role', '') != 'ADMIN':
            if not hasattr(user, 'midwife_profile'):
                return Response({'error': 'Only midwives can confirm appointments.'}, status=status.HTTP_403_FORBIDDEN)
            if user.midwife_profile != appointment.midwife:
                return Response({'error': 'You are not the assigned midwife for this appointment.'}, status=status.HTTP_403_FORBIDDEN)
            if user.midwife_profile.verification_status != MidwifeProfile.VerificationStatus.APPROVED:
                return Response({'error': 'Your midwife account is awaiting verification.'}, status=status.HTTP_403_FORBIDDEN)

        appointment.status = Appointment.AppointmentStatus.CONFIRMED
        appointment.save()

        try:
            from apps.consultations.models import Consultation
            Consultation.objects.get_or_create(
                appointment=appointment,
                defaults={
                    'user': appointment.user,
                    'midwife': appointment.midwife,
                    'consultation_type': appointment.appointment_type,
                    'status': Consultation.ConsultationStatus.SCHEDULED,
                }
            )
        except Exception as e:
            logger.warning(f"Failed to create consultation record for appointment {appointment.id}: {e}")

        try:
            _notify_user_and_midwife(appointment, action_type="APPOINTMENT_CONFIRMED")
        except Exception as e:
            logger.warning(f"Failed to dispatch confirmation notification for appointment {appointment.id}: {e}")

        return Response({'status': 'CONFIRMED', 'message': 'Appointment confirmed successfully.'}, status=status.HTTP_200_OK)

    @extend_schema(summary="Midwife action: Accept appointment (alias for confirm)", tags=["Appointments"])
    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        return self.confirm(request, pk=pk)

    @extend_schema(summary="Midwife action: Complete appointment", tags=["Appointments"])
    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        appointment = self.get_object()
        user = request.user
        if not user.is_staff and getattr(user, 'role', '') != 'ADMIN':
            if not hasattr(user, 'midwife_profile'):
                return Response({'error': 'Only midwives can complete appointments.'}, status=status.HTTP_403_FORBIDDEN)
            if user.midwife_profile != appointment.midwife:
                return Response({'error': 'You are not the assigned midwife for this appointment.'}, status=status.HTTP_403_FORBIDDEN)
            if user.midwife_profile.verification_status != MidwifeProfile.VerificationStatus.APPROVED:
                return Response({'error': 'Your midwife account is awaiting verification.'}, status=status.HTTP_403_FORBIDDEN)

        appointment.status = Appointment.AppointmentStatus.COMPLETED
        appointment.save()

        _notify_user_and_midwife(appointment, action_type="APPOINTMENT_COMPLETED")

        return Response({'status': 'COMPLETED', 'message': 'Appointment marked as completed.'}, status=status.HTTP_200_OK)

    @extend_schema(summary="Call Midwife: Check eligibility and retrieve dialer tel URI", tags=["Appointments"])
    @action(detail=True, methods=['get', 'post'], url_path='call-midwife')
    def call_midwife(self, request, pk=None):
        if not request.user or not request.user.is_authenticated:
            return Response({"detail": "Authentication credentials were not provided."}, status=status.HTTP_401_UNAUTHORIZED)

        appointment = Appointment.objects.select_related(
            'user', 'midwife', 'midwife__user', 'midwife__hospital'
        ).filter(id=pk).first()

        if not appointment:
            return Response({"error": "Appointment not found."}, status=status.HTTP_404_NOT_FOUND)

        from apps.appointments.call_service import AppointmentCallService
        data = AppointmentCallService.check_call_eligibility(appointment, request.user, request=request)

        if not data["is_authorized"]:
            return Response(
                {"error": "You do not have permission to access call details for this appointment.", "detail": data["reason"]},
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

