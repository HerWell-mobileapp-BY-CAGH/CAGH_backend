from rest_framework import serializers
from .models import Availability, TimeSlot, Appointment
from apps.users.user_serializers import UserSerializer
from apps.midwives.serializers import MidwifeProfileSerializer


class AvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Availability
        fields = '__all__'
        read_only_fields = ('id', 'midwife')


class TimeSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimeSlot
        fields = '__all__'
        read_only_fields = ('id', 'midwife')


class AppointmentSerializer(serializers.ModelSerializer):
    user_detail = UserSerializer(source='user', read_only=True)
    midwife_detail = MidwifeProfileSerializer(source='midwife', read_only=True)

    class Meta:
        model = Appointment
        fields = '__all__'
        read_only_fields = (
            'id', 'appointment_number', 'user', 'created_by', 'created_at', 'updated_at'
        )

    def validate(self, data):
        # Business rule check: Cancelled appointment cannot become active again
        if self.instance and self.instance.status == Appointment.AppointmentStatus.CANCELLED:
            if data.get('status') and data['status'] != Appointment.AppointmentStatus.CANCELLED:
                raise serializers.ValidationError("A cancelled appointment cannot be reactivated.")
        return data
