from datetime import date, datetime, timedelta
from rest_framework import serializers
from .models import Availability, TimeSlot, Appointment
from apps.users.user_serializers import UserSerializer
from apps.midwives.serializers import MidwifeProfileSerializer
from apps.midwives.models import MidwifeProfile


class AvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Availability
        fields = '__all__'
        read_only_fields = ('id', 'midwife', 'created_at', 'updated_at')

    def validate(self, data):
        target_date = data.get('date') or (self.instance.date if self.instance else None)
        start_time = data.get('start_time') or (self.instance.start_time if self.instance else None)
        end_time = data.get('end_time') or (self.instance.end_time if self.instance else None)
        methods = data.get('consultation_methods')
        if methods is None and self.instance:
            methods = self.instance.consultation_methods

        # Validate date is not in the past (for new instances)
        if not self.instance and target_date and target_date < date.today():
            raise serializers.ValidationError({"date": "Availability cannot be created for a past date."})

        # Validate start_time < end_time
        if start_time and end_time and start_time >= end_time:
            raise serializers.ValidationError({"start_time": "Start time must be earlier than end time."})

        # Validate consultation_methods
        if methods is not None:
            if not isinstance(methods, list) or len(methods) == 0:
                raise serializers.ValidationError({"consultation_methods": "At least one consultation method (e.g. IN_PERSON, VIRTUAL_VOICE) must be selected."})

            valid_choices = [c[0] for c in Appointment.AppointmentType.choices]
            invalid = [m for m in methods if m not in valid_choices]
            if invalid:
                raise serializers.ValidationError({"consultation_methods": f"Invalid consultation method(s): {', '.join(invalid)}. Must be one of {valid_choices}."})

        # Check for overlapping availability periods for the same midwife on the same date
        request = self.context.get('request')
        midwife = getattr(self.instance, 'midwife', None)
        if not midwife and request and hasattr(request.user, 'midwife_profile'):
            midwife = request.user.midwife_profile

        if midwife and target_date and start_time and end_time:
            overlapping = Availability.objects.filter(
                midwife=midwife,
                date=target_date,
                is_active=True,
                start_time__lt=end_time,
                end_time__gt=start_time,
            )
            if self.instance:
                overlapping = overlapping.exclude(id=self.instance.id)

            if overlapping.exists():
                raise serializers.ValidationError("An overlapping availability period already exists for this midwife on this date.")

        return data


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
        appointment_type = data.get('appointment_type') or (self.instance.appointment_type if self.instance else None)

        if midwife and scheduled_date and start_time and end_time:
            # Rule 2: Midwife must be APPROVED
            if midwife.verification_status != MidwifeProfile.VerificationStatus.APPROVED:
                raise serializers.ValidationError({"midwife": "Appointments can only be scheduled with verified & approved midwives."})

            # Rule 3: Check that appointment fits inside an active date-specific Availability period
            matching_availabilities = Availability.objects.filter(
                midwife=midwife,
                date=scheduled_date,
                is_active=True,
                start_time__lte=start_time,
                end_time__gte=end_time,
            )
            if not matching_availabilities.exists():
                raise serializers.ValidationError({
                    "start_time": "The requested time slot falls outside the midwife's configured availability on this date."
                })

            # Rule 4: Check that the availability period supports the requested appointment_type
            if appointment_type:
                supported = False
                for avail in matching_availabilities:
                    if appointment_type in (avail.consultation_methods or []):
                        supported = True
                        break
                if not supported:
                    raise serializers.ValidationError({
                        "appointment_type": f"The midwife does not offer '{appointment_type}' consultations during this availability period."
                    })

            # Rule 5: Prevent double-booking (overlapping appointments)
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

