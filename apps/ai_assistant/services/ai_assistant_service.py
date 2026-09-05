from typing import Dict, Any, Optional
from django.conf import settings
from rest_framework.exceptions import ValidationError

from ..models import AIConversation, AIMessage
from .safety_service import SafetyService, SafetyResult
from .knowledge_service import KnowledgeService
from .response_service import ResponseService
from .safety_validation_service import SafetyValidationService


class AIAssistantService:
    """
    FR-005 Main Orchestration Service for CAGH AI Assistant (Phase 1).
    Coordinates Safety Triage, Knowledge Retrieval, Conversation History,
    Response Generation, and Post-Safety Validation.
    """

    def __init__(self, response_service: Optional[ResponseService] = None):
        self.response_service = response_service or ResponseService()

    def process_chat_message(
        self,
        user,
        message_text: str,
        conversation_id: Optional[str] = None,
        language: str = "en"
    ) -> Dict[str, Any]:
        # 1. Input Validation
        max_len = getattr(settings, 'AI_MAX_INPUT_LENGTH', 1000)
        clean_text = message_text.strip() if message_text else ""
        if not clean_text:
            raise ValidationError({'message': 'Message text cannot be empty.'})
        if len(clean_text) > max_len:
            raise ValidationError({'message': f'Message exceeds maximum allowed length of {max_len} characters.'})

        # 2. Load or Create Conversation
        if conversation_id:
            try:
                conversation = AIConversation.objects.get(id=conversation_id, user=user)
            except (AIConversation.DoesNotExist, ValueError):
                raise ValidationError({'conversation_id': 'Invalid or inaccessible conversation ID.'})
        else:
            title = clean_text[:40] + ("..." if len(clean_text) > 40 else "")
            conversation = AIConversation.objects.create(user=user, title=title)

        # 3. Deterministic Tiered Safety Evaluation
        safety_result = SafetyService.evaluate(clean_text, user=user)

        # 4. Emergency / Urgent Bypass
        if safety_result.level in ['emergency', 'urgent']:
            emergency_response_text = SafetyService.generate_safety_response(safety_result, user=user)

            # Save User Message
            AIMessage.objects.create(
                conversation=conversation,
                role=AIMessage.MessageRole.USER,
                content=clean_text,
                category=safety_result.category,
                safety_level=safety_result.level,
                is_emergency=(safety_result.level == 'emergency')
            )

            # Save Assistant Emergency Response
            assistant_msg = AIMessage.objects.create(
                conversation=conversation,
                role=AIMessage.MessageRole.ASSISTANT,
                content=emergency_response_text,
                category=safety_result.category,
                safety_level=safety_result.level,
                is_emergency=(safety_result.level == 'emergency')
            )

            conversation.save()  # update updated_at timestamp

            return {
                "conversation_id": str(conversation.id),
                "message": {
                    "id": str(assistant_msg.id),
                    "role": assistant_msg.role,
                    "content": assistant_msg.content,
                    "category": assistant_msg.category,
                    "safety_level": assistant_msg.safety_level,
                    "is_emergency": assistant_msg.is_emergency,
                    "created_at": assistant_msg.created_at.isoformat(),
                },
                "safety": safety_result.to_dict()
            }

        # 5. Retrieve Approved CAGH Knowledge
        knowledge_context = KnowledgeService.retrieve_context(clean_text)

        # 6. Load Recent Conversation History
        max_history = getattr(settings, 'AI_MAX_HISTORY_MESSAGES', 6)
        recent_messages = conversation.messages.order_by('-created_at')[:max_history]
        history_list = [
            {"role": m.role, "content": m.content}
            for m in reversed(recent_messages)
        ]

        # 7. Generate Response using Active ResponseProvider
        try:
            raw_response = self.response_service.generate_response(
                message_text=clean_text,
                safety_result=safety_result,
                knowledge_context=knowledge_context,
                history=history_list,
                user=user,
                language=language
            )
        except Exception:
            raw_response = SafetyValidationService.get_safe_fallback()

        # 8. Safety Validation
        validated_response = SafetyValidationService.validate_response(raw_response)

        # 9. Save User Message & Assistant Message to Database
        AIMessage.objects.create(
            conversation=conversation,
            role=AIMessage.MessageRole.USER,
            content=clean_text,
            category=safety_result.category,
            safety_level=safety_result.level,
            is_emergency=False
        )

        assistant_msg = AIMessage.objects.create(
            conversation=conversation,
            role=AIMessage.MessageRole.ASSISTANT,
            content=validated_response,
            category=safety_result.category,
            safety_level=safety_result.level,
            is_emergency=False
        )

        conversation.save()

        # 10. Return Structured API Contract Response
        return {
            "conversation_id": str(conversation.id),
            "message": {
                "id": str(assistant_msg.id),
                "role": assistant_msg.role,
                "content": assistant_msg.content,
                "category": assistant_msg.category,
                "safety_level": assistant_msg.safety_level,
                "is_emergency": assistant_msg.is_emergency,
                "created_at": assistant_msg.created_at.isoformat(),
            },
            "safety": safety_result.to_dict()
        }
