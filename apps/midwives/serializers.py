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
    hospital_id = serializers.PrimaryKeyRelatedField(
        queryset=Hospital.objects.all(), source='hospital', required=False, allow_null=True, write_only=True
    )
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
        extra_kwargs = {
            'license_number': {'required': False, 'allow_blank': True, 'allow_null': True},
            'experience_years': {'required': False},
            'languages': {'required': True, 'allow_blank': False},
        }

    def validate(self, attrs):
        instance = getattr(self, 'instance', None)
        partial = getattr(self, 'partial', False)
        errors = {}

        # Require full document credentials only for full creation/PUT requests
        if not partial:
            cv_file = attrs.get('cv_file', getattr(instance, 'cv_file', None) if instance else None)
            hospital = attrs.get('hospital', instance.hospital if instance else None)
            languages = attrs.get('languages', instance.languages if instance else None)

            if not cv_file:
                errors['cv_file'] = "CV / Resume document file is required."
            if not hospital:
                errors['hospital'] = "Affiliated Hospital facility is required."
            if not languages or not str(languages).strip():
                errors['languages'] = "Spoken languages field is required."

        # Sensitive credentials lock for approved midwives
        request = self.context.get('request')
        is_admin = request and request.user and (request.user.is_staff or getattr(request.user, 'role', '') == 'ADMIN')

        if instance and instance.verification_status == MidwifeProfile.VerificationStatus.APPROVED and not is_admin:
            if 'license_number' in attrs and attrs['license_number'] != instance.license_number:
                errors['license_number'] = "Medical license number is locked after approval. Contact Admin to update official credentials."
            if 'cv_file' in attrs and attrs['cv_file'] != instance.cv_file:
                errors['cv_file'] = "CV document is locked after approval. Contact Admin to update official credentials."
            if 'hospital' in attrs and attrs['hospital'] != instance.hospital:
                errors['hospital'] = "Affiliated hospital is locked after approval. Contact Admin to update official credentials."

        if errors:
            raise serializers.ValidationError(errors)

        return attrs

    def get_is_favorite(self, obj):
        request = self.context.get('request')
        if not request or not request.user or not request.user.is_authenticated:
            return False

        if 'saved_midwife_ids' not in self.context:
            self.context['saved_midwife_ids'] = set(
                SavedMidwife.objects.filter(user=request.user).values_list('midwife_id', flat=True)
            )

        return obj.id in self.context['saved_midwife_ids']


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

