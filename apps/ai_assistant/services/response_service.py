from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from .safety_service import SafetyResult


class ResponseProvider(ABC):
    """
    Abstract Response Provider interface.
    Allows plugging in KnowledgeResponseProvider (Phase 1) or GeminiResponseProvider (Phase 2)
    without modifying API contracts, serializers, or frontend views.
    """

    @abstractmethod
    def generate_response(
        self,
        message_text: str,
        safety_result: SafetyResult,
        knowledge_context: str,
        history: List[Dict[str, Any]],
        user=None,
        language: str = "en"
    ) -> str:
        pass


class KnowledgeResponseProvider(ResponseProvider):
    """
    Phase 1 Response Provider:
    Generates structured, evidence-based, CAGH-approved answers from retrieved knowledge
    and Ethiopian MoH Guidelines without calling external LLM APIs.
    """

    def generate_response(
        self,
        message_text: str,
        safety_result: SafetyResult,
        knowledge_context: str,
        history: List[Dict[str, Any]],
        user=None,
        language: str = "en"
    ) -> str:
        first_name = (getattr(user, 'first_name', '') or '').strip() if user else ''
        greeting = f"Hello {first_name}! " if first_name else ""

        # If knowledge context exists, format it cleanly with CAGH header
        if knowledge_context:
            return (
                f"🌸 **{greeting}HerWell Educational Guidance**\n\n"
                f"Based on CAGH-approved health knowledge and official Ethiopian Ministry of Health (FMoH 2022) Guidelines:\n\n"
                f"{knowledge_context}\n\n"
                "### 💡 Next Steps:\n"
                "• Explore the **Learning Center** for full articles and interactive guides.\n"
                "• Schedule a direct consultation with a verified midwife for individualized clinical evaluation.\n\n"
                "⚠️ *Disclaimer: Information provided is for educational guidance only and does not replace professional medical diagnosis or treatment.*"
            )

        # Structured safe educational fallback
        return (
            f"🌸 **{greeting}HerWell Reproductive & Women's Health Education**\n\n"
            f"Thank you for reaching out regarding your query.\n\n"
            "HerWell provides trusted health education grounded in the official **Ethiopian Ministry of Health (FMoH 2022)** Guidelines for Adolescent Girls and Young Women.\n\n"
            "### 🌸 Suggested Topics to Explore:\n"
            "• **Menstrual Health**: Period pain relief, cycle tracking, and menstrual hygiene.\n"
            "• **Nutrition & Anemia**: Iron-rich diets (teff, gomen) and IFA supplements.\n"
            "• **Dual Protection**: Using condoms alongside LARCs (implants/IUDs) for pregnancy and STI prevention.\n\n"
            "### 🩺 Midwife Consultation:\n"
            "You can schedule a private audio/video consultation with an accredited midwife directly in the app.\n\n"
            "⚠️ *Disclaimer: Educational guidance only. Please consult a qualified health provider for medical diagnosis.*"
        )


class ResponseService:
    """
    Response Manager that delegates generation to the configured ResponseProvider.
    In Phase 1, defaults to KnowledgeResponseProvider.
    """

    def __init__(self, provider: Optional[ResponseProvider] = None):
        self.provider = provider or KnowledgeResponseProvider()

    def generate_response(
        self,
        message_text: str,
        safety_result: SafetyResult,
        knowledge_context: str,
        history: List[Dict[str, Any]],
        user=None,
        language: str = "en"
    ) -> str:
        return self.provider.generate_response(
            message_text=message_text,
            safety_result=safety_result,
            knowledge_context=knowledge_context,
            history=history,
            user=user,
            language=language
        )
