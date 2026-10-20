from rest_framework import serializers
from .models import Consultation, ConsultationNote, VoiceSession
from apps.users.user_serializers import UserSerializer
from apps.midwives.serializers import MidwifeProfileSerializer
from apps.appointments.models import Appointment


class ConsultationNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsultationNote
        fields = '__all__'
        read_only_fields = ('id', 'consultation', 'midwife', 'created_at', 'updated_at')


class VoiceSessionSerializer(serializers.ModelSerializer):
    caller_detail = UserSerializer(source='caller', read_only=True)

    class Meta:
        model = VoiceSession
        fields = '__all__'
        read_only_fields = ('id', 'consultation', 'caller')


class ConsultationSerializer(serializers.ModelSerializer):
    user_detail = UserSerializer(source='user', read_only=True)
    midwife_detail = MidwifeProfileSerializer(source='midwife', read_only=True)
    notes = ConsultationNoteSerializer(many=True, read_only=True)
    voice_session = VoiceSessionSerializer(read_only=True)
    call_eligibility = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Consultation
        fields = '__all__'
        read_only_fields = ('id', 'user', 'midwife', 'consultation_type', 'created_at', 'updated_at')

    def get_call_eligibility(self, obj):
        request = self.context.get('request')
        user = getattr(request, 'user', None) if request else None
        if not user or not user.is_authenticated or not obj.appointment:
            return None
        from apps.appointments.call_service import AppointmentCallService
        return AppointmentCallService.check_call_eligibility(obj.appointment, user, request=request)

    def validate_appointment(self, appointment):
        if appointment.status != Appointment.AppointmentStatus.CONFIRMED:
            raise serializers.ValidationError("Consultation requires a confirmed appointment.")
        return appointment

