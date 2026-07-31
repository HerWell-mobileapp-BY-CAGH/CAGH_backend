from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import AIQuestion
from .serializers import AIQuestionSerializer


class AIQuestionViewSet(viewsets.ModelViewSet):
    queryset = AIQuestion.objects.all()
    serializer_class = AIQuestionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return AIQuestion.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        question_text = serializer.validated_data.get('question')
        # Placeholder for AI health assistant logic integration
        simulated_response = (
            f"Thank you for asking: '{question_text}'. "
            "This is a maternal healthcare guidance response. "
            "Always consult your midwife or doctor for medical emergencies."
        )
        serializer.save(user=self.request.user, response=simulated_response)

    @action(detail=True, methods=['post'])
    def submit_feedback(self, request, pk=None):
        ai_q = self.get_object()
        feedback_val = request.data.get('feedback')  # LIKE or DISLIKE
        if feedback_val in [AIQuestion.FeedbackStatus.LIKE, AIQuestion.FeedbackStatus.DISLIKE]:
            ai_q.feedback = feedback_val
            ai_q.save()
            return Response({'status': 'Feedback recorded successfully'})
        return Response({'error': 'Invalid feedback option.'}, status=status.HTTP_400_BAD_REQUEST)
