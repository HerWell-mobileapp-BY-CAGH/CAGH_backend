from rest_framework import serializers
from .models import Hospital, MidwifeProfile, Qualification, Certificate, Expertise, SavedMidwife, BlockedDate
from apps.users.user_serializers import UserSerializer


class HospitalSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hospital
        fields = '__all__'


class QualificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Qualification
        fields = '__all__'
        read_only_fields = ('id', 'midwife')


class CertificateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Certificate
        fields = '__all__'
        read_only_fields = ('id', 'midwife', 'is_verified')


class ExpertiseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expertise
        fields = '__all__'


class BlockedDateSerializer(serializers.ModelSerializer):
    class Meta:
        model = BlockedDate
        fields = '__all__'
        read_only_fields = ('id', 'midwife', 'created_at')


class MidwifeProfileSerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    hospital = HospitalSerializer(read_only=True)
    qualifications = QualificationSerializer(many=True, read_only=True)
    certificates = CertificateSerializer(many=True, read_only=True)
    expertises = ExpertiseSerializer(many=True, read_only=True)
    is_favorite = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = MidwifeProfile
        fields = '__all__'
        read_only_fields = (
            'id', 'user', 'verification_status', 'verified_at',
            'verified_by', 'rejection_reason', 'created_at', 'updated_at'
        )

    def get_is_favorite(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            return SavedMidwife.objects.filter(user=request.user, midwife=obj).exists()
        return False


class SavedMidwifeSerializer(serializers.ModelSerializer):
    midwife_detail = MidwifeProfileSerializer(source='midwife', read_only=True)

    class Meta:
        model = SavedMidwife
        fields = '__all__'
        read_only_fields = ('id', 'user', 'created_at')


class MidwifeDashboardSerializer(serializers.Serializer):
    verification_status = serializers.CharField()
    today_schedule = serializers.ListField()
    upcoming_appointments = serializers.ListField()
    pending_requests = serializers.ListField()
    recent_history = serializers.ListField()
    counts = serializers.DictField()

