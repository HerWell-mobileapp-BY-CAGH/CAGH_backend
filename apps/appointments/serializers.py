from rest_framework import serializers
from .models import Availability, TimeSlot, Appointment
from apps.users.user_serializers import UserSerializer
from apps.midwives.serializers import MidwifeProfileSerializer


from apps.midwives.models import MidwifeProfile, BlockedDate


class AvailabilitySerializer(serializers.ModelSerializer):
    day_name = serializers.CharField(source='get_day_of_week_display', read_only=True)

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
        # Rule 1: Cancelled appointment cannot become active again
        if self.instance and self.instance.status == Appointment.AppointmentStatus.CANCELLED:
            if data.get('status') and data['status'] != Appointment.AppointmentStatus.CANCELLED:
                raise serializers.ValidationError("A cancelled appointment cannot be reactivated.")

        midwife = data.get('midwife') or (self.instance.midwife if self.instance else None)
        scheduled_date = data.get('scheduled_date') or (self.instance.scheduled_date if self.instance else None)
        start_time = data.get('start_time') or (self.instance.start_time if self.instance else None)
        end_time = data.get('end_time') or (self.instance.end_time if self.instance else None)

        if midwife and scheduled_date and start_time and end_time:
            # Rule 2: Midwife must be APPROVED
            if midwife.verification_status != MidwifeProfile.VerificationStatus.APPROVED:
                raise serializers.ValidationError({"midwife": "Appointments can only be scheduled with verified & approved midwives."})

            # Rule 3: Midwife cannot have a BlockedDate on scheduled_date
            if BlockedDate.objects.filter(midwife=midwife, date=scheduled_date).exists():
                raise serializers.ValidationError({"scheduled_date": "The midwife is unavailable (on leave or holiday) on this selected date."})

            # Rule 4: Prevent double-booking (overlapping appointments)
            overlapping = Appointment.objects.filter(
                midwife=midwife,
                scheduled_date=scheduled_date,
                status__in=[Appointment.AppointmentStatus.PENDING, Appointment.AppointmentStatus.CONFIRMED],
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            if self.instance:
                overlapping = overlapping.exclude(id=self.instance.id)

            if overlapping.exists():
                raise serializers.ValidationError("This time slot is already booked for another appointment. Please choose a different time.")

        return data

