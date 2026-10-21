from rest_framework import serializers
from .models import (
    Facility,
    AuditLog,
    Report,
    TranslationKey,
    TranslationValue,
    TranslationVersion,
)


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


class TranslationValueSerializer(serializers.ModelSerializer):
    key_name = serializers.CharField(source='key.key', read_only=True)
    category = serializers.CharField(source='key.category', read_only=True)

    class Meta:
        model = TranslationValue
        fields = ('id', 'key_name', 'category', 'language', 'value', 'status', 'updated_at')


class TranslationDictionaryResponseSerializer(serializers.Serializer):
    language = serializers.CharField(help_text="Language code e.g. 'am'")
    version = serializers.IntegerField(help_text="Current translation schema version integer")
    up_to_date = serializers.BooleanField(help_text="True if client supplied version is already current")
    count = serializers.IntegerField(help_text="Number of translations returned")
    translations = serializers.DictField(
        child=serializers.CharField(),
        help_text="Dictionary of key -> translated string pairs"
    )


class TranslationValueManageSerializer(serializers.ModelSerializer):
    key_name = serializers.CharField(source='key.key', read_only=True)

    class Meta:
        model = TranslationValue
        fields = ('id', 'key', 'key_name', 'language', 'value', 'status', 'reviewed_by', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')


class TranslationKeyManageSerializer(serializers.ModelSerializer):
    translations = TranslationValueSerializer(many=True, read_only=True)

    class Meta:
        model = TranslationKey
        fields = ('id', 'key', 'default_text', 'category', 'description', 'translations', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')



