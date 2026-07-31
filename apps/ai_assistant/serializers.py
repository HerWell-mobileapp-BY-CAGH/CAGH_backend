from rest_framework import serializers
from .models import AIQuestion


class AIQuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIQuestion
        fields = '__all__'
        read_only_fields = ('id', 'user', 'response', 'created_at')
