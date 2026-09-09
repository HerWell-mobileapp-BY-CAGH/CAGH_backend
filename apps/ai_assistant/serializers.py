from rest_framework import serializers
from .models import AIQuestion, AIConversation, AIMessage
from .services import SafetyService


class AIQuestionSerializer(serializers.ModelSerializer):
    disclaimer = serializers.SerializerMethodField(read_only=True)
    suggested_next_questions = serializers.SerializerMethodField(read_only=True)
    safety_result = serializers.SerializerMethodField(read_only=True)

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

    def get_safety_result(self, obj):
        res = SafetyService.evaluate(obj.question, user=obj.user)
        return res.to_dict()


class AIMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIMessage
        fields = ('id', 'role', 'content', 'category', 'safety_level', 'is_emergency', 'created_at')
        read_only_fields = ('id', 'role', 'content', 'category', 'safety_level', 'is_emergency', 'created_at')


class AIConversationSerializer(serializers.ModelSerializer):
    messages = AIMessageSerializer(many=True, read_only=True)

    class Meta:
        model = AIConversation
        fields = ('id', 'title', 'created_at', 'updated_at', 'messages')
        read_only_fields = ('id', 'created_at', 'updated_at', 'messages')


class AIChatRequestSerializer(serializers.Serializer):
    conversation_id = serializers.UUIDField(required=False, allow_null=True)
    message = serializers.CharField(required=True, max_length=1000)
    language = serializers.CharField(required=False, default='en', max_length=10)


class AIChatResponseSerializer(serializers.Serializer):
    conversation_id = serializers.UUIDField()
    message = AIMessageSerializer()
    safety = serializers.DictField()

