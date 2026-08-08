from rest_framework import serializers
from .models import Review
from apps.users.user_serializers import UserSerializer
from apps.consultations.models import Consultation



class ReviewSerializer(serializers.ModelSerializer):
    reviewer_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Review
        fields = '__all__'
        read_only_fields = ('id', 'user', 'created_at', 'updated_at')

    def get_reviewer_name(self, obj):
        if obj.is_anonymous:
            return "Anonymous"
        return f"{obj.user.first_name} {obj.user.last_name}".strip() or obj.user.username

    def validate_consultation(self, consultation):
        if consultation and consultation.status != Consultation.ConsultationStatus.COMPLETED:
            raise serializers.ValidationError("Reviews can only be left for completed consultations.")
        return consultation
