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
    document_file_url = serializers.SerializerMethodField()

    class Meta:
        model = Certificate
        fields = '__all__'
        read_only_fields = ('id', 'midwife', 'is_verified')

    def get_document_file_url(self, obj):
        if not obj.document_file:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.document_file.url)
        return obj.document_file.url


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
            'verified_by', 'rejection_reason', 'suspension_reason',
            'created_at', 'updated_at'
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


class AdminReviewerSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    username = serializers.CharField()
    email = serializers.EmailField(allow_null=True)
    full_name = serializers.SerializerMethodField()

    def get_full_name(self, obj):
        profile = getattr(obj, "profile", None)
        if profile and (profile.first_name or profile.last_name):
            return f"{profile.first_name} {profile.last_name}".strip()
        return obj.username or obj.email or str(obj.id)


class MidwifeApplicationDetailSerializer(MidwifeProfileSerializer):
    """Full midwife registration payload for admin review."""

    cv_file_url = serializers.SerializerMethodField()
    verified_by_detail = AdminReviewerSerializer(source="verified_by", read_only=True)
    certificates = CertificateSerializer(many=True, read_only=True)

    class Meta(MidwifeProfileSerializer.Meta):
        fields = (
            "id", "user", "hospital", "hospital_id", "license_number", "bio",
            "experience_years", "languages", "cv_file", "cv_file_url",
            "offered_consultation_types", "verification_status", "verified_at",
            "verified_by", "verified_by_detail", "rejection_reason", "suspension_reason", "specialty",
            "consultation_fee", "is_accepting_bookings", "rating_average",
            "rating_count", "created_at", "updated_at", "qualifications",
            "certificates", "expertises", "is_favorite",
        )
        read_only_fields = MidwifeProfileSerializer.Meta.read_only_fields

    def get_cv_file_url(self, obj):
        if not obj.cv_file:
            return None
        request = self.context.get("request")
        if request:
            return request.build_absolute_uri(obj.cv_file.url)
        return obj.cv_file.url


class MidwifeReviewActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["APPROVE", "REJECT", "SUSPEND"])
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
        help_text="Required when action is REJECT or SUSPEND.",
    )

    def validate(self, attrs):
        if attrs["action"] in ("REJECT", "SUSPEND") and not str(attrs.get("reason", "")).strip():
            action_label = "rejecting" if attrs["action"] == "REJECT" else "suspending"
            raise serializers.ValidationError(
                {"reason": f"A reason is required when {action_label} a midwife account."}
            )
        return attrs

