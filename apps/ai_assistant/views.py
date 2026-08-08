from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema

from .models import AIQuestion
from .serializers import AIQuestionSerializer


def _detect_emergency(question_text):
    """Detects critical red-flag emergency keywords in user health queries."""
    emergency_keywords = [
        'severe bleeding', 'heavy bleeding', 'hemorrhage', 'fainting', 'unconscious',
        'severe abdominal pain', 'acute pain', 'chest pain', 'convulsion', 'seizure',
        'difficulty breathing', 'self harm', 'emergency', 'sos', 'fluid leaking',
    ]
    lowered = question_text.lower()
    return any(kw in lowered for kw in emergency_keywords)


def _generate_ai_health_response(question_text):
    """
    FR-005 AI Safety & Educational Knowledge Engine.
    Generates trusted, evidence-based reproductive health guidance.
    Enforces medical disclaimer and directs to verified midwives.
    """
    if _detect_emergency(question_text):
        return (
            "🚨 **URGENT EMERGENCY ALERT**\n\n"
            "Your question describes symptoms that require **immediate emergency medical evaluation**.\n\n"
            "• Please go to the nearest hospital or health center emergency room immediately.\n"
            "• You can also use the app's **SOS Emergency** feature to alert your saved emergency contacts.\n"
            "• Contact local emergency services or call national health hotline (+251 907).\n\n"
            "⚠️ *Disclaimer: This AI Assistant does not replace emergency medical care.*"
        )

    lowered = question_text.lower()

    if any(k in lowered for k in ['cramp', 'period', 'menstruat', 'cycle']):
        return (
            "**Menstrual Health & Self-Care Guidance:**\n\n"
            "Menstrual cramps (dysmenorrhea) occur as the uterine muscles contract. Here are evidence-based self-care steps:\n"
            "1. **Warm Compress**: Apply a heating pad or hot water bottle to your lower abdomen.\n"
            "2. **Hydration & Dietary Care**: Drink warm water or chamomile tea, and eat magnesium-rich foods (bananas, leafy greens).\n"
            "3. **Light Physical Activity**: Gentle stretching or walking helps release endorphins that naturally relieve pain.\n\n"
            "💡 *When to consult a midwife*: If your cramps are debilitating, accompany heavy clot bleeding, or interfere with daily life, please schedule a consultation with a verified midwife on our platform."
        )

    elif any(k in lowered for k in ['pregnan', 'trimester', 'baby', 'fetus', 'anc', 'antenatal']):
        return (
            "**Pregnancy & Antenatal Care (ANC) Guidance:**\n\n"
            "During pregnancy, proper nutrition and regular ANC checkups are essential for both mother and baby:\n"
            "1. **Key Nutrients**: Take daily iron and folic acid supplements as advised by your healthcare provider.\n"
            "2. **Hydration**: Drink 8–10 glasses of water daily to maintain amniotic fluid levels.\n"
            "3. **Regular ANC Visits**: Attend at least 4 WHO-recommended antenatal checkups.\n\n"
            "💡 *Next Steps*: You can view nearby verified health facilities or book a voice/video consultation with an approved midwife directly through this app!"
        )

    elif any(k in lowered for k in ['contracept', 'family plan', 'pill', 'iud', 'condom', 'birth control']):
        return (
            "**Contraception & Family Planning Overview:**\n\n"
            "Family planning empowers you to make informed reproductive choices:\n"
            "1. **Barrier Methods**: Condoms protect against both pregnancy and STIs/HIV.\n"
            "2. **Hormonal Methods**: Oral contraceptive pills, implants, or injections regulated by prescription.\n"
            "3. **Long-Acting Reversible Contraception (LARC)**: Intrauterine Devices (IUDs).\n\n"
            "💡 *Recommendation*: Different contraceptive methods suit different health profiles. Book a consultation with a verified midwife for personalized counseling."
        )

    elif any(k in lowered for k in ['breastfeed', 'lactat', 'postnatal', 'postpartum']):
        return (
            "**Postnatal & Breastfeeding Care Guidance:**\n\n"
            "1. **Exclusive Breastfeeding**: Recommended for the first 6 months of life.\n"
            "2. **Latch Technique**: Ensure baby takes both the nipple and a large part of the areola to prevent nipple soreness.\n"
            "3. **Maternal Recovery**: Rest adequately and maintain balanced nutrition rich in protein and fluids.\n\n"
            "💡 *Recommendation*: If you experience breast pain or fever, consult a midwife promptly to check for mastitis."
        )

    else:
        return (
            f"**Reproductive & Women's Health Education:**\n\n"
            f"Thank you for asking about: *'{question_text}'*.\n\n"
            "HerWell AI provides general health education to empower women and adolescent girls with evidence-based guidance. "
            "For personalized clinical advice, physical examination, or treatment plans, we encourage you to book a direct consultation with one of our verified midwives or visit a nearby health facility.\n\n"
            "⚠️ *Disclaimer: Responses are for educational purposes only.*"
        )


class AIQuestionViewSet(viewsets.ModelViewSet):
    """
    3.2 AI Health Assistant Module (Floating AI Assistant)
    FR-005: Conversational Reproductive & Women's Health Education, AI Safety,
    Suggested Questions, and Thumbs Up / Down Feedback.
    """

    queryset = AIQuestion.objects.all()
    serializer_class = AIQuestionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return AIQuestion.objects.filter(user=self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        question_text = serializer.validated_data.get('question', '')
        ai_response = _generate_ai_health_response(question_text)
        serializer.save(user=self.request.user, response=ai_response)

    @extend_schema(summary="Ask floating AI Health Assistant a question", tags=["AI Assistant"])
    @action(detail=False, methods=['post'])
    def ask(self, request):
        question_text = request.data.get('question')
        if not question_text:
            return Response({'error': 'Question text is required.'}, status=status.HTTP_400_BAD_REQUEST)

        ai_response = _generate_ai_health_response(question_text)
        ai_q = AIQuestion.objects.create(
            user=request.user,
            question=question_text,
            response=ai_response,
        )

        serializer = self.get_serializer(ai_q)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Get curated suggested questions for Floating AI UI", tags=["AI Assistant"])
    @action(detail=False, methods=['get'], url_path='suggested-questions')
    def suggested_questions(self, request):
        prompts = [
            "What are healthy nutrition tips during the first trimester of pregnancy?",
            "How can I relieve severe menstrual cramps naturally?",
            "What warning signs require immediate emergency care during pregnancy?",
            "How do I track my ovulation and fertile window accurately?",
            "What contraceptive options are safe while breastfeeding?",
        ]
        return Response({
            'count': len(prompts),
            'suggested_questions': prompts,
        }, status=status.HTTP_200_OK)

    @extend_schema(summary="Submit Thumbs Up or Thumbs Down feedback", tags=["AI Assistant"])
    @action(detail=True, methods=['post'])
    def feedback(self, request, pk=None):
        ai_q = self.get_object()
        feedback_val = request.data.get('feedback', '').upper()

        valid_choices = ['THUMBS_UP', 'THUMBS_DOWN', 'LIKE', 'DISLIKE']
        if feedback_val in valid_choices:
            if feedback_val == 'LIKE':
                feedback_val = 'THUMBS_UP'
            elif feedback_val == 'DISLIKE':
                feedback_val = 'THUMBS_DOWN'

            ai_q.feedback = feedback_val
            ai_q.save()
            return Response({'status': 'FEEDBACK_RECORDED', 'feedback': ai_q.feedback}, status=status.HTTP_200_OK)

        return Response({'error': 'Invalid feedback value. Use THUMBS_UP or THUMBS_DOWN.'}, status=status.HTTP_400_BAD_REQUEST)

