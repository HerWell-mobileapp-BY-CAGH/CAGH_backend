import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class SafetyResult:
    level: str  # "emergency", "urgent", "normal"
    category: str  # "self_harm", "pregnancy_warning", "general_emergency", "sexual_reproductive_health", "menstrual_health", "general_health"
    matched_rules: List[str] = field(default_factory=list)
    confidence: str = "high"  # "high", "medium", "low"
    requires_sos: bool = False
    priority: int = 0
    recommended_action: str = "KNOWLEDGE_ANSWER"  # "IMMEDIATE_EMERGENCY", "URGENT_CLINICAL_CARE", "KNOWLEDGE_ANSWER"

    def to_dict(self):
        return asdict(self)


class SafetyService:
    """
    FR-005 Deterministic, Context-Aware, Tiered Safety Engine for HerWell/CAGH.
    
    Triage Hierarchy:
    1. SELF_HARM_IMMEDIATE        (Priority 100, EMERGENCY, requires_sos=True)
    2. SEVERE_PREGNANCY_WARNING   (Priority 90, EMERGENCY, requires_sos=True)
    3. GENERAL_EMERGENCY          (Priority 80, EMERGENCY, requires_sos=True)
    4. URGENT_PREGNANCY_WARNING   (Priority 75, URGENT, requires_sos=True)
    5. URGENT_HEALTH_RISK         (Priority 70, URGENT, requires_sos=False)
    6. NORMAL / EDUCATIONAL       (Priority 0, NORMAL, requires_sos=False)
    """

    @staticmethod
    def normalize_text(text: str) -> str:
        """Standardizes input text by removing punctuation, extra whitespace, and converting to lowercase."""
        if not text:
            return ""
        normalized = text.lower()
        normalized = re.sub(r'[^\w\s]', ' ', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        return normalized

    @classmethod
    def evaluate(cls, text: str, user=None) -> SafetyResult:
        normalized = cls.normalize_text(text)
        if not normalized:
            return SafetyResult(
                level="normal",
                category="general_health",
                matched_rules=["empty_input"],
                confidence="high",
                requires_sos=False,
                priority=0,
                recommended_action="KNOWLEDGE_ANSWER"
            )

        matched_results: List[SafetyResult] = []

        # Detect pregnancy context & educational inquiry patterns
        is_pregnant_context = any(k in normalized for k in ['pregnant', 'pregnancy', 'trimester', 'baby in stomach', 'expecting'])
        is_educational_inquiry = any(k in normalized for k in [
            'what causes', 'causes of', 'why do', 'what are the warning signs', 'what are signs', 'signs of',
            'what are the symptoms', 'symptoms of', 'how to prevent', 'my sister', 'my friend', 'in general',
            'definition of', 'how common is', 'is it normal to', 'what does it mean when', 'can you explain',
            'tell me about'
        ]) and not any(k in normalized for k in ['right now', 'i am bleeding', 'i have severe', 'help me', 'soaking pads right now', 'kill myself'])

        # ---------------------------------------------------------------------
        # Priority 100: SELF_HARM_IMMEDIATE (EMERGENCY)
        # ---------------------------------------------------------------------
        self_harm_keywords = ['suicide', 'kill myself', 'want to die', 'end my life', 'self harm', 'cut myself', 'harming myself']
        if any(kw in normalized for kw in self_harm_keywords):
            matched_results.append(SafetyResult(
                level="emergency",
                category="self_harm",
                matched_rules=["self_harm_immediate"],
                confidence="high",
                requires_sos=True,
                priority=100,
                recommended_action="IMMEDIATE_EMERGENCY"
            ))

        if not is_educational_inquiry:
            # ---------------------------------------------------------------------
            # Priority 90: SEVERE_PREGNANCY_WARNING (EMERGENCY)
            # ---------------------------------------------------------------------
            severe_bleeding = any(k in normalized for k in ['severe bleeding', 'bleeding heavily', 'heavy bleeding', 'hemorrhage', 'soaking pads', 'passing clots', 'blood gushing'])
            severe_pain = any(k in normalized for k in ['severe abdominal pain', 'acute abdominal pain', 'acute belly pain', 'unbearable pain', 'extreme pain'])
            no_movement = any(k in normalized for k in ['no fetal movement', 'baby stopped moving', 'baby not kicking'])
            leaking_fluid = any(k in normalized for k in ['water broke early', 'fluid leaking', 'amniotic fluid'])

            if (is_pregnant_context and (severe_bleeding or severe_pain or no_movement or leaking_fluid)) or (severe_bleeding and severe_pain):
                matched_rules = []
                if severe_bleeding: matched_rules.append("severe_pregnancy_bleeding")
                if severe_pain: matched_rules.append("severe_pregnancy_pain")
                if no_movement: matched_rules.append("no_fetal_movement")
                if leaking_fluid: matched_rules.append("premature_fluid_leak")

                matched_results.append(SafetyResult(
                    level="emergency",
                    category="pregnancy_warning",
                    matched_rules=matched_rules or ["severe_pregnancy_warning"],
                    confidence="high",
                    requires_sos=True,
                    priority=90,
                    recommended_action="IMMEDIATE_EMERGENCY"
                ))

            # ---------------------------------------------------------------------
            # Priority 80: GENERAL_EMERGENCY (EMERGENCY)
            # ---------------------------------------------------------------------
            gen_emergency_keywords = [
                'bleeding heavily', 'hemorrhage', 'severe abdominal pain', 'acute abdominal pain',
                'fainting', 'unconscious', 'passed out', 'convulsion', 'seizure',
                'difficulty breathing', 'cannot breathe', 'shortness of breath',
                'chest pain', 'severe assault', 'rape', 'sexual violence', 'forced sex',
                'high fever with stiff neck', 'pre eclampsia', 'eclampsia'
            ]
            if any(kw in normalized for kw in gen_emergency_keywords):
                matched_kw = [kw for kw in gen_emergency_keywords if kw in normalized]
                matched_results.append(SafetyResult(
                    level="emergency",
                    category="general_emergency",
                    matched_rules=matched_kw,
                    confidence="high",
                    requires_sos=True,
                    priority=80,
                    recommended_action="IMMEDIATE_EMERGENCY"
                ))

        # ---------------------------------------------------------------------
        # Priority 75: URGENT_PREGNANCY_WARNING (URGENT)
        # ---------------------------------------------------------------------
        persistent_pain = any(k in normalized for k in ['persistent pain', 'ongoing abdominal pain', 'cramping during pregnancy', 'lower stomach pain', 'abdominal pain'])
        preeclampsia_signs = any(k in normalized for k in ['swallowing face', 'swollen face', 'swollen hands', 'blurred vision', 'seeing spots'])

        if is_pregnant_context and (persistent_pain or preeclampsia_signs):
            matched_kw = []
            if persistent_pain: matched_kw.append("persistent_pregnancy_abdominal_pain")
            if preeclampsia_signs: matched_kw.append("preeclampsia_warning_signs")

            matched_results.append(SafetyResult(
                level="urgent",
                category="pregnancy_warning",
                matched_rules=matched_kw,
                confidence="high",
                requires_sos=False,
                priority=75,
                recommended_action="URGENT_CLINICAL_CARE"
            ))

        # ---------------------------------------------------------------------
        # Priority 70: URGENT_HEALTH_RISK (URGENT)
        # ---------------------------------------------------------------------
        urgent_health_keywords = [
            'foul discharge', 'high fever', 'pelvic pain', 'severe dysmenorrhea',
            'suspected ectopic', 'soaking 2 pads per hour', 'pep emergency', 'hiv exposure'
        ]
        if any(kw in normalized for kw in urgent_health_keywords):
            matched_kw = [kw for kw in urgent_health_keywords if kw in normalized]
            matched_results.append(SafetyResult(
                level="urgent",
                category="sexual_reproductive_health",
                matched_rules=matched_kw,
                confidence="high",
                requires_sos=False,
                priority=70,
                recommended_action="URGENT_CLINICAL_CARE"
            ))

        # ---------------------------------------------------------------------
        # Priority Winner Selection (Highest Priority Rule Wins!)
        # ---------------------------------------------------------------------
        if matched_results:
            matched_results.sort(key=lambda x: x.priority, reverse=True)
            return matched_results[0]

        # ---------------------------------------------------------------------
        # Priority 0: NORMAL (EDUCATIONAL / KNOWLEDGE BASE)
        # ---------------------------------------------------------------------
        category = "general_health"
        if any(k in normalized for k in ['period', 'menstrual', 'cramp', 'pad', 'menarche', 'cycle']):
            category = "menstrual_health"
        elif any(k in normalized for k in ['pill', 'implant', 'iud', 'condom', 'depo', 'birth control', 'contracept']):
            category = "sexual_reproductive_health"
        elif any(k in normalized for k in ['anemia', 'iron', 'teff', 'gomen', 'nutrition', 'food', 'diet']):
            category = "general_health"

        return SafetyResult(
            level="normal",
            category=category,
            matched_rules=["educational_query"],
            confidence="high",
            requires_sos=False,
            priority=0,
            recommended_action="KNOWLEDGE_ANSWER"
        )

    @classmethod
    def generate_safety_response(cls, safety_result: SafetyResult, user=None) -> str:
        """Generates the appropriate deterministic markdown response for Emergency or Urgent safety results."""
        first_name = (getattr(user, 'first_name', '') or '').strip() if user else ''
        greeting = f"Hello {first_name}! " if first_name else ""

        if safety_result.level == "emergency":
            return (
                f"🚨 **URGENT EMERGENCY MEDICAL ALERT**\n\n"
                f"{greeting}Your query indicates critical red-flag symptoms requiring **immediate clinical evaluation**:\n\n"
                "### 🚨 Immediate Emergency Steps:\n"
                "1. **Proceed to Hospital**: Go to the nearest emergency room or health center immediately.\n"
                "2. **Activate In-App SOS**: Press the **SOS Emergency** button in the app to broadcast your location to saved emergency contacts.\n"
                "3. **Call National Emergency Line**: Contact emergency service dispatch or call **+251 907**.\n"
                "4. **Post-Assault / Crisis Care**: Emergency Contraception (within 120h) and HIV PEP (within 72h) are available urgently at health facilities.\n\n"
                "⚠️ *Disclaimer: HerWell AI Assistant is an educational tool and cannot replace emergency clinical diagnosis.*"
            )

        elif safety_result.level == "urgent":
            return (
                f"⚠️ **URGENT CLINICAL ADVISORY**\n\n"
                f"{greeting}Your query describes symptoms that require **prompt clinical evaluation** by a qualified midwife or healthcare provider:\n\n"
                "### 🩺 Recommended Clinical Steps:\n"
                "1. **Consult a Verified Midwife**: Use the HerWell app to book an urgent audio/video consultation with an approved midwife.\n"
                "2. **Visit a Health Center**: If symptoms worsen (such as severe bleeding, fainting, or acute pain), proceed to the nearest clinic immediately.\n"
                "3. **In-App Emergency SOS**: If you feel unsafe or experience a sudden medical decline, tap the **SOS Emergency** button.\n\n"
                "⚠️ *Disclaimer: Educational guidance only. Please seek professional medical care promptly.*"
            )

        return ""
