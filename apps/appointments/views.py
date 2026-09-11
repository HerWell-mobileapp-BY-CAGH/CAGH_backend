from datetime import datetime, timedelta
from django.db import models
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import Availability, TimeSlot, Appointment
from .serializers import AvailabilitySerializer, TimeSlotSerializer, AppointmentSerializer
from apps.midwives.models import MidwifeProfile, BlockedDate
from apps.notifications.models import Notification


def _notify_user_and_midwife(appointment, title, body, action_type="APPOINTMENT_UPDATE"):
    """
    Sends in-app notifications to both the patient and assigned midwife.
    """
    # Patient Notification
    Notification.objects.create(
        user=appointment.user,
        title=title,
        body=body,
        type="APPOINTMENT",
        action=action_type,
        reference_id=str(appointment.id),
    )

    # Midwife Notification
    if appointment.midwife and appointment.midwife.user:
        Notification.objects.create(
            user=appointment.midwife.user,
            title=title,
            body=body,
            type="APPOINTMENT",
            action=action_type,
            reference_id=str(appointment.id),
        )


class AvailabilityViewSet(viewsets.ModelViewSet):
    """
    Manages midwife working hours availability schedules.
    """

    queryset = Availability.objects.all()
    serializer_class = AvailabilitySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if hasattr(self.request.user, 'midwife_profile'):
            return Availability.objects.filter(midwife=self.request.user.midwife_profile)
        return Availability.objects.filter(is_active=True)

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


class TimeSlotViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Generates available 30-minute time slots for a midwife on a target date,
    accounting for working hours, blocked dates, and existing bookings.
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

        # Check if date is blocked by midwife
        if BlockedDate.objects.filter(midwife=midwife, date=target_date).exists():
            return Response(
                {"available": False, "reason": "Midwife is on leave / holiday on this date.", "slots": []},
                status=status.HTTP_200_OK,
            )

        # Get day of week (0 = Monday, 6 = Sunday)
        day_of_week = target_date.weekday()
        availabilities = Availability.objects.filter(midwife=midwife, day_of_week=day_of_week, is_active=True)

        if not availabilities.exists():
            return Response(
                {"available": False, "reason": "Midwife has no working hours scheduled for this day of week.", "slots": []},
                status=status.HTTP_200_OK,
            )

        # Get existing appointments for midwife on this date
        booked_appointments = Appointment.objects.filter(
            midwife=midwife,
            scheduled_date=target_date,
            status__in=[Appointment.AppointmentStatus.PENDING, Appointment.AppointmentStatus.CONFIRMED],
        )

        generated_slots = []
        for avail in availabilities:
            curr_start = datetime.combine(target_date, avail.start_time)
            curr_end = datetime.combine(target_date, avail.end_time)

            while curr_start + timedelta(minutes=30) <= curr_end:
                slot_start_time = curr_start.time()
                slot_end_time = (curr_start + timedelta(minutes=30)).time()

                # Check if slot overlaps with any booked appointment
                is_booked = booked_appointments.filter(
                    start_time__lt=slot_end_time,
                    end_time__gt=slot_start_time,
                ).exists()

                generated_slots.append({
                    "date": date_str,
                    "start_time": slot_start_time.strftime("%H:%M"),
                    "end_time": slot_end_time.strftime("%H:%M"),
                    "start_time_12h": slot_start_time.strftime("%I:%M %p"),
                    "end_time_12h": slot_end_time.strftime("%I:%M %p"),
                    "start_time_ethiopian": _to_ethiopian_time(slot_start_time),
                    "end_time_ethiopian": _to_ethiopian_time(slot_end_time),
                    "is_available": not is_booked,
                })

                curr_start += timedelta(minutes=30)

        morning_slots = [s for s in generated_slots if 9 <= int(s["start_time"].split(":")[0]) < 12]
        afternoon_slots = [s for s in generated_slots if 12 <= int(s["start_time"].split(":")[0]) < 17]
        evening_slots = [s for s in generated_slots if 17 <= int(s["start_time"].split(":")[0]) < 21]

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

    queryset = Appointment.objects.all().select_related('user', 'midwife', 'midwife__user')
    serializer_class = AppointmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = Appointment.objects.all().select_related('user', 'midwife', 'midwife__user')

        if user.is_staff or getattr(user, 'role', '') == 'ADMIN':
            return queryset

        if hasattr(user, 'midwife_profile'):
            return queryset.filter(models.Q(user=user) | models.Q(midwife=user.midwife_profile))

        return queryset.filter(user=user)

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
        _notify_user_and_midwife(
            appointment,
            title="New Appointment Scheduled",
            body=(
                f"Appointment {appointment.appointment_number} scheduled for {appointment.scheduled_date} "
                f"at {appointment.start_time.strftime('%H:%M')} ({appointment.get_appointment_type_display()})."
            ),
            action_type="APPOINTMENT_BOOKED",
        )

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
        _notify_user_and_midwife(
            appointment,
            title="Appointment Cancelled",
            body=f"Appointment {appointment.appointment_number} scheduled for {appointment.scheduled_date} has been cancelled.",
            action_type="APPOINTMENT_CANCELLED",
        )

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
        _notify_user_and_midwife(
            updated_apt,
            title="Appointment Rescheduled",
            body=(
                f"Appointment {updated_apt.appointment_number} rescheduled to {updated_apt.scheduled_date} "
                f"at {updated_apt.start_time}."
            ),
            action_type="APPOINTMENT_RESCHEDULED",
        )

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

        _notify_user_and_midwife(
            appointment,
            title="Appointment Confirmed",
            body=f"Your appointment {appointment.appointment_number} with Midwife {appointment.midwife.user.username} is confirmed.",
            action_type="APPOINTMENT_CONFIRMED",
        )

        return Response({'status': 'CONFIRMED', 'message': 'Appointment confirmed successfully.'}, status=status.HTTP_200_OK)

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

        _notify_user_and_midwife(
            appointment,
            title="Appointment Completed",
            body=f"Consultation appointment {appointment.appointment_number} has been completed.",
            action_type="APPOINTMENT_COMPLETED",
        )

        return Response({'status': 'COMPLETED', 'message': 'Appointment marked as completed.'}, status=status.HTTP_200_OK)

