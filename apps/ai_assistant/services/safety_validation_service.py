import re


class SafetyValidationService:
    """
    FR-005 Post-Generation Safety Validation Service for CAGH AI Assistant.
    Inspects responses before returning them to ensure no definitive medical diagnosis,
    drug prescription, or dangerous self-treatment claims exist.
    """

    UNSAFE_PATTERNS = [
        r'\byou have\s+(?:cancer|hiv|syphilis|gonorrhea|tuberculosis|chlamydia)\b',
        r'\bdiagnosed with\b',
        r'\btake\s+\d+\s*mg\b',
        r'\bprescribe\s+(?:antibiotic|medication|drug|pill)\b',
        r'\bdo not go to (?:a |the )?hospital\b',
        r'\bignore your doctor\b',
    ]

    @classmethod
    def validate_response(cls, response_text: str) -> str:
        if not response_text:
            return cls.get_safe_fallback()

        lowered = response_text.lower()
        for pattern in cls.UNSAFE_PATTERNS:
            if re.search(pattern, lowered):
                return cls.get_safe_fallback()

        return response_text

    @classmethod
    def get_safe_fallback(cls) -> str:
        return (
            "🌸 **HerWell Educational Health Guidance**\n\n"
            "Thank you for your question. HerWell AI provides general reproductive health education based on Ethiopian MoH guidelines.\n\n"
            "For specific medical evaluation, physical diagnosis, or prescription services, please consult a verified midwife or visit your nearest health facility.\n\n"
            "⚠️ *Disclaimer: Information provided is for educational guidance only.*"
        )
