from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db import models
from .models import Availability, TimeSlot, Appointment
from .serializers import AvailabilitySerializer, TimeSlotSerializer, AppointmentSerializer


class AvailabilityViewSet(viewsets.ModelViewSet):
    queryset = Availability.objects.all()
    serializer_class = AvailabilitySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if hasattr(self.request.user, 'midwife_profile'):
            return Availability.objects.filter(midwife=self.request.user.midwife_profile)
        return Availability.objects.all()

    def perform_create(self, serializer):
        if hasattr(self.request.user, 'midwife_profile'):
            serializer.save(midwife=self.request.user.midwife_profile)


class TimeSlotViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = TimeSlot.objects.all()
    serializer_class = TimeSlotSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        queryset = TimeSlot.objects.filter(is_available=True)
        midwife_id = self.request.query_params.get('midwife_id')
        date_param = self.request.query_params.get('date')
        if midwife_id:
            queryset = queryset.filter(midwife_id=midwife_id)
        if date_param:
            queryset = queryset.filter(date=date_param)
        return queryset


class AppointmentViewSet(viewsets.ModelViewSet):
    queryset = Appointment.objects.all()
    serializer_class = AppointmentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if hasattr(user, 'midwife_profile'):
            return Appointment.objects.filter(models.Q(user=user) | models.Q(midwife=user.midwife_profile))
        return Appointment.objects.filter(user=user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user, created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        appointment = self.get_object()
        appointment.status = Appointment.AppointmentStatus.CANCELLED
        appointment.save()
        return Response({'status': 'Appointment cancelled'})

    @action(detail=True, methods=['post'])
    def reschedule(self, request, pk=None):
        appointment = self.get_object()
        new_date = request.data.get('scheduled_date')
        new_start = request.data.get('start_time')
        new_end = request.data.get('end_time')

        if not new_date or not new_start or not new_end:
            return Response(
                {'error': 'scheduled_date, start_time, and end_time are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        appointment.scheduled_date = new_date
        appointment.start_time = new_start
        appointment.end_time = new_end
        appointment.status = Appointment.AppointmentStatus.PENDING
        appointment.save()
        return Response({'status': 'Appointment rescheduled successfully'})
