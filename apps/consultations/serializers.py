from rest_framework import serializers
from .models import Consultation, ConsultationNote, VoiceSession, VideoSession
from apps.users.user_serializers import UserSerializer
from apps.midwives.serializers import MidwifeProfileSerializer
from apps.appointments.models import Appointment


class ConsultationNoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConsultationNote
        fields = '__all__'
        read_only_fields = ('id', 'consultation', 'midwife', 'created_at', 'updated_at')


class VoiceSessionSerializer(serializers.ModelSerializer):
    rtc_channel_name = serializers.SerializerMethodField()
    rtc_token = serializers.SerializerMethodField()
    ws_signaling_url = serializers.SerializerMethodField()

    class Meta:
        model = VoiceSession
        fields = '__all__'
        read_only_fields = ('id', 'consultation')

    def get_rtc_channel_name(self, obj):
        return f"cagh_voice_{obj.session_key}"

    def get_rtc_token(self, obj):
        # Generates deterministic WebRTC / Agora RTC connection token for session key
        return f"RTC_TOKEN_{obj.session_key}"

    def get_ws_signaling_url(self, obj):
        return f"ws://localhost:8000/ws/consultation/{obj.consultation_id}/"


class VideoSessionSerializer(serializers.ModelSerializer):
    rtc_channel_name = serializers.SerializerMethodField()
    rtc_token = serializers.SerializerMethodField()
    ws_signaling_url = serializers.SerializerMethodField()

    class Meta:
        model = VideoSession
        fields = '__all__'
        read_only_fields = ('id', 'consultation')

    def get_rtc_channel_name(self, obj):
        return f"cagh_video_{obj.session_key}"

    def get_rtc_token(self, obj):
        return f"RTC_TOKEN_{obj.session_key}"

    def get_ws_signaling_url(self, obj):
        return f"ws://localhost:8000/ws/consultation/{obj.consultation_id}/"



class ConsultationSerializer(serializers.ModelSerializer):
    user_detail = UserSerializer(source='user', read_only=True)
    midwife_detail = MidwifeProfileSerializer(source='midwife', read_only=True)
    notes = ConsultationNoteSerializer(many=True, read_only=True)
    voice_session = VoiceSessionSerializer(read_only=True)
    video_session = VideoSessionSerializer(read_only=True)

    class Meta:
        model = Consultation
        fields = '__all__'
        read_only_fields = ('id', 'user', 'midwife', 'consultation_type', 'created_at', 'updated_at')

    def validate_appointment(self, appointment):
        if appointment.status != Appointment.AppointmentStatus.CONFIRMED:
            raise serializers.ValidationError("Consultation requires a confirmed appointment.")
        return appointment

