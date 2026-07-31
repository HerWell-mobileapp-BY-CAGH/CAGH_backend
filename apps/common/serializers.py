from rest_framework import serializers
from .models import Facility, AuditLog, Report


class FacilitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Facility
        fields = '__all__'


class AuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditLog
        fields = '__all__'
        read_only_fields = ('id', 'timestamp')


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = '__all__'
        read_only_fields = ('id', 'reporter', 'status', 'created_at')


class LanguageSelectionSerializer(serializers.Serializer):
    language = serializers.CharField(
        required=True,
        help_text="Language code ('en', 'am') or name ('English', 'Amharic')."
    )

