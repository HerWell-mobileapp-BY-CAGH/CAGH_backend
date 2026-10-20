from datetime import date, datetime, timedelta
from rest_framework import serializers
from .models import Availability, TimeSlot, Appointment
from apps.users.user_serializers import UserSerializer
from apps.midwives.serializers import MidwifeProfileSerializer
from apps.midwives.models import MidwifeProfile


from django.utils import timezone


class AvailabilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Availability
        fields = '__all__'
        read_only_fields = ('id', 'midwife', 'created_at', 'updated_at')

    def to_internal_value(self, data):
        if hasattr(data, 'dict'):
            data = data.dict()
        else:
            data = dict(data)

        # Handle aliases and flexible input formats for consultation_methods
        raw_methods = (
            data.get('consultation_methods')
            or data.get('consultation_method')
            or data.get('methods')
            or data.get('offered_consultation_types')
        )

        if raw_methods is not None:
            parsed_methods = []
            if isinstance(raw_methods, str):
                import json
                raw_methods_str = raw_methods.strip()
                if raw_methods_str.startswith('[') and raw_methods_str.endswith(']'):
                    try:
                        raw_methods = json.loads(raw_methods_str)
                    except Exception:
                        raw_methods = [m.strip() for m in raw_methods_str[1:-1].split(',')]
                else:
                    raw_methods = [m.strip() for m in raw_methods_str.split(',')]

            if isinstance(raw_methods, list):
                for item in raw_methods:
                    if not isinstance(item, str):
                        continue
                    clean = item.strip().upper().replace('-', '_').replace(' ', '_')
                    if clean in ['IN_PERSON', 'IN_PERSON_CONSULTATION', 'INPERSON']:
                        parsed_methods.append('IN_PERSON')
                    elif clean in ['VIRTUAL_VOICE', 'VIRTUAL_VOICE_CONSULTATION', 'VOICE_CALL', 'VOICE', 'VIRTUALVOICE']:
                        parsed_methods.append('VIRTUAL_VOICE')
                    elif clean in ['VIRTUAL_VIDEO', 'VIRTUAL_VIDEO_CONSULTATION', 'VIDEO_CALL', 'VIDEO', 'VIRTUALVIDEO']:
                        parsed_methods.append('VIRTUAL_VIDEO')
                    elif clean in [c[0] for c in Appointment.AppointmentType.choices]:
                        parsed_methods.append(clean)

            if parsed_methods:
                data['consultation_methods'] = list(dict.fromkeys(parsed_methods))
            elif isinstance(raw_methods, list):
                data['consultation_methods'] = raw_methods

        return super().to_internal_value(data)

    def validate(self, data):
        target_date = data.get('date') or (self.instance.date if self.instance else None)
        if isinstance(target_date, datetime):
            target_date = target_date.date()

        start_time = data.get('start_time') or (self.instance.start_time if self.instance else None)
        end_time = data.get('end_time') or (self.instance.end_time if self.instance else None)
        methods = data.get('consultation_methods')
        if methods is None and self.instance:
            methods = self.instance.consultation_methods

        request = self.context.get('request')
        midwife = getattr(self.instance, 'midwife', None)
        if not midwife and request and hasattr(request.user, 'midwife_profile'):
            midwife = request.user.midwife_profile

        # Default consultation_methods for new instance if missing or empty
        if not self.instance and (methods is None or len(methods) == 0):
            if midwife and getattr(midwife, 'offered_consultation_types', None):
                methods = list(midwife.offered_consultation_types)
            else:
                methods = ["IN_PERSON", "VIRTUAL_VOICE"]
            data['consultation_methods'] = methods

        today = timezone.localdate()
        now_time = timezone.localtime().time()

        # Validate date is not in the past (for both creation and update)
        if target_date and target_date < today:
            raise serializers.ValidationError({"date": "Availability cannot be created or updated for a past date."})

        # Validate start_time for today's date (must be strictly later than current local time)
        if target_date == today and start_time and start_time <= now_time:
            raise serializers.ValidationError({"start_time": "Start time must be strictly later than the current time for today's availability."})

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
                raise serializers.ValidationError({"start_time": "An overlapping availability period already exists for this midwife on this date."})

        return data


class TimeSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimeSlot
        fields = '__all__'
        read_only_fields = ('id', 'midwife')


class AppointmentSerializer(serializers.ModelSerializer):
    user_detail = UserSerializer(source='user', read_only=True)
    midwife_detail = MidwifeProfileSerializer(source='midwife', read_only=True)
    call_eligibility = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Appointment
        fields = '__all__'
        read_only_fields = (
            'id', 'appointment_number', 'user', 'created_by', 'created_at', 'updated_at'
        )

    def get_call_eligibility(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        if not user or not user.is_authenticated:
            return None
        from apps.appointments.call_service import AppointmentCallService
        return AppointmentCallService.check_call_eligibility(obj, user, request=request)

    def to_internal_value(self, data):
        if hasattr(data, 'dict'):
            data = data.dict()
        else:
            data = dict(data)

        # Alias 1: midwife_id -> midwife
        if 'midwife_id' in data and 'midwife' not in data:
            data['midwife'] = data['midwife_id']

        # Alias 2: date -> scheduled_date
        if 'date' in data and 'scheduled_date' not in data:
            data['scheduled_date'] = data['date']

        # Alias 3: appointment_type / type / consultation_type / consultation_method handling
        apt_type = (
            data.get('appointment_type')
            or data.get('type')
            or data.get('consultation_type')
            or data.get('consultation_method')
        )
        if apt_type and isinstance(apt_type, str):
            clean_type = apt_type.strip().upper().replace('-', '_').replace(' ', '_')
            if clean_type in ['IN_PERSON', 'IN_PERSON_CONSULTATION', 'INPERSON']:
                data['appointment_type'] = 'IN_PERSON'
            elif clean_type in ['VIRTUAL_VOICE', 'VIRTUAL_VOICE_CONSULTATION', 'VOICE_CALL', 'VOICE', 'VIRTUALVOICE']:
                data['appointment_type'] = 'VIRTUAL_VOICE'
            elif clean_type in ['VIRTUAL_VIDEO', 'VIRTUAL_VIDEO_CONSULTATION', 'VIDEO_CALL', 'VIDEO', 'VIRTUALVIDEO']:
                data['appointment_type'] = 'VIRTUAL_VIDEO'
            else:
                data['appointment_type'] = clean_type

        # Alias 4: availability_id / availability lookup
        avail_id = data.get('availability_id') or data.get('availability') or data.get('slot_id')
        if avail_id:
            try:
                avail = Availability.objects.get(id=avail_id)
                if 'midwife' not in data:
                    data['midwife'] = str(avail.midwife.id)
                if 'scheduled_date' not in data:
                    data['scheduled_date'] = avail.date.strftime("%Y-%m-%d")
                if 'start_time' not in data:
                    data['start_time'] = avail.start_time.strftime("%H:%M:%S")
                if 'end_time' not in data:
                    data['end_time'] = avail.end_time.strftime("%H:%M:%S")
            except (Availability.DoesNotExist, ValueError):
                pass

        return super().to_internal_value(data)

    def validate(self, data):
        # Rule 1: Cancelled appointment cannot become active again
        if self.instance and self.instance.status == Appointment.AppointmentStatus.CANCELLED:
            if data.get('status') and data['status'] != Appointment.AppointmentStatus.CANCELLED:
                raise serializers.ValidationError({"status": "A cancelled appointment cannot be reactivated."})

        midwife = data.get('midwife') or (self.instance.midwife if self.instance else None)
        scheduled_date = data.get('scheduled_date') or (self.instance.scheduled_date if self.instance else None)
        start_time = data.get('start_time') or (self.instance.start_time if self.instance else None)
        end_time = data.get('end_time') or (self.instance.end_time if self.instance else None)
        appointment_type = data.get('appointment_type') or (self.instance.appointment_type if self.instance else None)

        if not midwife:
            raise serializers.ValidationError({"midwife": "Midwife profile ID is required to schedule an appointment."})
        if not scheduled_date:
            raise serializers.ValidationError({"scheduled_date": "Scheduled date (YYYY-MM-DD) is required."})
        if not start_time or not end_time:
            raise serializers.ValidationError({"start_time": "Start time and end time are required to book an appointment."})

        if start_time >= end_time:
            raise serializers.ValidationError({"start_time": "Start time must be earlier than end time."})

        today = timezone.localdate()
        if not self.instance and scheduled_date and scheduled_date < today:
            raise serializers.ValidationError({"scheduled_date": "Appointments cannot be booked for past dates."})

        # Rule 2: Midwife must be APPROVED
        if midwife.verification_status != MidwifeProfile.VerificationStatus.APPROVED:
            raise serializers.ValidationError({"midwife": "Appointments can only be scheduled with verified & approved midwives."})

        if getattr(midwife, 'is_accepting_bookings', True) is False:
            raise serializers.ValidationError({"midwife": "This midwife is currently not accepting new appointment bookings."})

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
                "start_time": f"No active availability period found for Midwife {midwife.user.username} on {scheduled_date} covering {start_time.strftime('%H:%M')}–{end_time.strftime('%H:%M')}."
            })

        # Rule 4: Check that the availability period supports the requested appointment_type
        if appointment_type:
            supported = False
            for avail in matching_availabilities:
                raw_avail_methods = avail.consultation_methods or ["IN_PERSON", "VIRTUAL_VOICE"]
                normalized_avail_methods = []
                for m in raw_avail_methods:
                    clean = str(m).strip().upper().replace('-', '_').replace(' ', '_')
                    if clean in ['IN_PERSON', 'IN_PERSON_CONSULTATION', 'INPERSON']:
                        normalized_avail_methods.append('IN_PERSON')
                    elif clean in ['VIRTUAL_VOICE', 'VIRTUAL_VOICE_CONSULTATION', 'VOICE_CALL', 'VOICE', 'VIRTUALVOICE']:
                        normalized_avail_methods.append('VIRTUAL_VOICE')
                    elif clean in ['VIRTUAL_VIDEO', 'VIRTUAL_VIDEO_CONSULTATION', 'VIDEO_CALL', 'VIDEO', 'VIRTUALVIDEO']:
                        normalized_avail_methods.append('VIRTUAL_VIDEO')
                    else:
                        normalized_avail_methods.append(clean)

                if appointment_type in normalized_avail_methods:
                    supported = True
                    break

            if not supported:
                raise serializers.ValidationError({
                    "appointment_type": f"The midwife does not offer '{appointment_type}' consultations during the selected availability period."
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
            raise serializers.ValidationError({
                "non_field_errors": ["This time slot is already booked for another appointment. Please choose a different time."]
            })

        return data

