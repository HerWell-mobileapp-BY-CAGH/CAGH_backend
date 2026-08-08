from rest_framework import serializers
from .models import AIQuestion


class AIQuestionSerializer(serializers.ModelSerializer):
    disclaimer = serializers.SerializerMethodField(read_only=True)
    suggested_next_questions = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = AIQuestion
        fields = '__all__'
        read_only_fields = ('id', 'user', 'response', 'created_at')

    def get_disclaimer(self, obj):
        return "⚠️ Disclaimer: This response is for educational purposes only and does not substitute professional medical advice."

    def get_suggested_next_questions(self, obj):
        return [
            "Would you like to book a consultation with a verified midwife?",
            "What self-care or nutrition tips apply to this condition?",
            "What warning signs require immediate emergency care?",
        ]

