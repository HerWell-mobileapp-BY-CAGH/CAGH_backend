from rest_framework import serializers
from .models import Facility, AuditLog, Report


class FacilitySerializer(serializers.ModelSerializer):
    distance_km = serializers.SerializerMethodField()

    class Meta:
        model = Facility
        fields = '__all__'

    def get_distance_km(self, obj):
        return getattr(obj, 'distance_km', None)



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

