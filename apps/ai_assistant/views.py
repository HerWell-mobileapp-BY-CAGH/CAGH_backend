from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.throttling import UserRateThrottle
from drf_spectacular.utils import extend_schema

from .models import AIQuestion, AIConversation, AIMessage
from .serializers import (
    AIQuestionSerializer,
    AIConversationSerializer,
    AIMessageSerializer,
    AIChatRequestSerializer,
    AIChatResponseSerializer
)
from .services import SafetyService, AIAssistantService


def _generate_ai_health_response(question_text, user=None):
    """
    Tiered Safety & Educational Knowledge Engine for HerWell/CAGH.
    Engineered based on Ethiopian Ministry of Health (FMoH 2022) Guidelines.

    Features:
    - Tiered Deterministic Safety Triage (Priority 100 Self-Harm, 90 Severe Pregnancy, 80 General Emergency, 70 Urgent Risk)
    - Structured SafetyResult Dataclass Integration
    - Context-Aware Keyword & Combination Scoring
    - User Role Context Awareness (Patient vs Midwife/Provider)
    """
    is_midwife = user and (getattr(user, 'role', '') == 'MIDWIFE' or hasattr(user, 'midwife_profile'))
    first_name = (getattr(user, 'first_name', '') or '').strip() if user else ''
    greeting = f"Hello {first_name}! " if first_name else ""

    # 1. Deterministic Tiered Safety Evaluation (Highest Priority Rule Wins!)
    safety_result = SafetyService.evaluate(question_text, user=user)

    # 2. Emergency or Urgent Triage Bypass
    if safety_result.level in ['emergency', 'urgent']:
        return SafetyService.generate_safety_response(safety_result, user=user)

    clean_text = SafetyService.normalize_text(question_text)

    # Detect casual greetings, test inputs, gibberish (e.g. "shhh", "hi", "hello", "test", "ok", "asdf", "lol", "hey")
    casual_words = ['shhh', 'shh', 'sh', 'hi', 'hello', 'hey', 'test', 'testing', 'ok', 'okay', 'asdf', 'lol', 'yo', 'sup', 'hm', 'hmm', 'hmmm', 'a', 'b', 'c', '123', '???', '...']
    if len(clean_text) <= 3 or clean_text in casual_words or not any(c.isalpha() for c in clean_text):
        role_note = " (Provider Portal Mode)" if is_midwife else ""
        return (
            f"👋 **{greeting}Welcome to HerWell Health AI Assistant!{role_note}**\n\n"
            "I am your personal, confidential health companion grounded in the official Ethiopian Ministry of Health (FMoH 2022) Guidelines.\n\n"
            "### 🌸 How Can I Assist You Today?\n"
            "You can ask me questions about any of the following health topics:\n\n"
            "• 🩸 **Menstrual Health & Pain**: Relieving cramps, tracking cycles, or menstrual pad hygiene.\n"
            "• 🍏 **Nutrition & Anemia**: Iron-rich diets (teff, gomen), IFA supplements, and healthy growth.\n"
            "• 🛡️ **Contraception & Dual Protection**: Implants, IUDs, emergency pills, or condom protection.\n"
            "• 🔬 **STI & Cervical Health**: HPV vaccination schedules, STI symptoms, and confidential screening.\n"
            "• 🤰 **Pregnancy & Antenatal Care (ANC)**: First trimester visits, nutrition, and birth readiness.\n"
            "• 👶 **Postnatal & Infant Care**: Exclusive breastfeeding, colostrum, and newborn checkups.\n\n"
            "💡 *Try asking*: *\"How can I relieve period pain naturally?\"* or *\"What is Dual Protection?\"*\n\n"
            "⚠️ *Disclaimer: HerWell AI provides educational guidance and does not replace direct clinical consultation.*"
        )

    # ---------------------------------------------------------------------------
    # Micro-Unit Knowledge Mapping
    # ---------------------------------------------------------------------------
    topic_matches = []

    # 1. Emergency Contraceptive Pills (ECPs)
    if any(k in clean_text for k in ['morning after', 'emergency pill', 'ecp', 'p2', 'postpill', 'after unprotected']):
        topic_matches.append((
            "**Emergency Contraceptive Pills (ECPs) Guidance:**\n\n"
            "ECPs prevent unintended pregnancy after unprotected sex, condom failure, or missed pills.\n\n"
            "### ⏰ Critical Timelines:\n"
            "• **Peak Efficacy**: Take within **24 hours** of unprotected sex for maximum protection (>95% effective).\n"
            "• **Maximum Window**: Can be taken up to **72 to 120 hours (3–5 days)**, though effectiveness decreases over time.\n\n"
            "### 📌 Essential Instructions:\n"
            "1. **Vomiting Management**: If you vomit within **2 hours** of taking the pill, take another dose immediately.\n"
            "2. **No Future Protection**: ECPs do NOT protect against subsequent sex acts in the same cycle. Use condoms or start a regular method.\n"
            "3. **No STI Protection**: ECPs do not prevent STIs or HIV. Seek clinical STI screening if at risk.\n\n"
            "💡 *Next Steps*: Schedule a private video/audio consultation with an approved midwife to discuss long-term contraceptive options."
        ))

    # 2. Emergency IUD
    if any(k in clean_text for k in ['emergency iud', 'copper iud emergency', 'emergency iucd']):
        topic_matches.append((
            "**Emergency Copper IUD (Cu-IUD) Guidance:**\n\n"
            "The Copper IUD is the single **most effective emergency contraceptive method** available.\n\n"
            "### 🌟 Key Features & Timelines:\n"
            "• **Insertion Window**: Must be inserted by a trained midwife or doctor within **5 days (120 hours)** of unprotected intercourse.\n"
            "• **99.9% Effectiveness**: Reduces pregnancy risk by >99.9% when inserted within 5 days.\n"
            "• **Dual Benefit**: Instantly converts into a regular, highly effective contraceptive method lasting up to **12 years**.\n\n"
            "💡 *Action*: Visit a nearby accredited health center or book a midwife on HerWell for urgent insertion."
        ))

    # 3. Implants
    if any(k in clean_text for k in ['implant', 'implanon', 'jadelle', 'arm rod', 'matchstick pill']):
        topic_matches.append((
            "**Contraceptive Implants (Implanon / Jadelle) Overview:**\n\n"
            "Implants are small, flexible rods inserted under the skin of the inner upper arm.\n\n"
            "### 🌿 Key Clinical Facts:\n"
            "• **Lifespan**: Implanon protects for **3 years**; Jadelle protects for **5 years**.\n"
            "• **>99% Efficacy**: One of the most reliable methods; requires no daily action.\n"
            "• **Reversibility**: Full fertility returns **immediately** after removal by a trained health worker.\n"
            "• **Bleeding Changes**: Irregular spotting or lighter/stopped periods are common, safe side effects.\n\n"
            "💡 *Procedure*: Requires minor numbing injection for arm insertion. Book a consultation with a verified midwife!"
        ))

    # 4. IUD / IUCD
    if any(k in clean_text for k in ['iud', 'iucd', 'copper t', 'mirena', 'levonorgestrel iud', 'coil']):
        topic_matches.append((
            "**Intrauterine Devices (Copper T & Hormonal IUD) Guidance:**\n\n"
            "An IUD is a small T-shaped device placed inside the uterus by a skilled provider.\n\n"
            "### 🔍 Types of IUDs:\n"
            "1. **Copper T (TCu-380A)**: Non-hormonal, effective for up to **12 years**. Prevents fertilization via copper ions.\n"
            "2. **Hormonal IUD (Levonorgestrel / Mirena)**: Releases progestin locally, effective for **5 years**. Makes periods significantly lighter and less painful.\n\n"
            "### 📌 Maintenance:\n"
            "• Gently check your IUD strings once a month after your period.\n"
            "• If strings feel longer/shorter or you feel hard plastic, consult your midwife.\n\n"
            "💡 *Midwife Consultation*: Book an appointment to evaluate IUD suitability or schedule insertion."
        ))

    # 5. Injectables (Depo-Provera)
    if any(k in clean_text for k in ['depo', 'depo-provera', 'injectable', 'injection birth control', '3 month shot']):
        topic_matches.append((
            "**Injectable Contraceptive (Depo-Provera) Guidance:**\n\n"
            "Depo-Provera is a progestin injection given into the arm or buttock muscle.\n\n"
            "### 💉 Key Clinical Instructions:\n"
            "• **Dosing Schedule**: Given once every **3 months (13 weeks)**. You have a 2-week grace window.\n"
            "• **Amenorrhea**: Most women experience lighter or stopped periods after 6–12 months of use.\n"
            "• **Fertility Return**: Delayed return of fertility (takes an average of 7–10 months after stopping injections).\n"
            "• **Bone Health**: Maintain adequate calcium and Vitamin D intake through diet and exercise.\n\n"
            "💡 *Reminder*: Set an alert on your calendar for your next 3-month injection date!"
        ))

    # 6. Oral Pills (OCPs)
    if any(k in clean_text for k in ['oral pill', 'ocp', 'daily pill', 'birth control pill', 'combined pill', 'missed pill']):
        topic_matches.append((
            "**Oral Contraceptive Pills (OCPs) Self-Care & Missed Pill Rules:**\n\n"
            "Daily contraceptive pills require consistent habits for high protection.\n\n"
            "### 💊 Daily Rules:\n"
            "1. **Same Time Daily**: Take 1 pill every day at the exact same hour.\n"
            "2. **Missed 1 Pill**: Take the missed pill immediately as remembered, even if it means taking 2 pills in one day.\n"
            "3. **Missed 2+ Pills**: Take the most recent missed pill, discard older missed pills, and use condoms as backup for **7 consecutive days**.\n\n"
            "💡 *Recommendation*: Connect with a verified midwife for pill prescriptions and managing minor side effects like mild nausea."
        ))

    # 7. Condom Usage
    if any(k in clean_text for k in ['condom', 'female condom', 'rubber', 'latex', 'protection sex']):
        topic_matches.append((
            "**Condom Usage & Protection Guidelines:**\n\n"
            "Condoms are the **ONLY** contraceptive method that protects against both pregnancy AND STIs/HIV.\n\n"
            "### 🛡️ Correct Usage Steps:\n"
            "1. **Check Expiry & Packaging**: Ensure packet is sealed with an air bubble and not expired.\n"
            "2. **Put on Before Contact**: Roll condom down to the base of the erect penis before any genital contact.\n"
            "3. **Pinch the Tip**: Leave half an inch at the tip to trap semen and prevent air tears.\n"
            "4. **Water-Based Lubricant**: Use ONLY water-based or silicone lubricants. Oil-based lubricants (vaseline, body lotion) break latex condoms.\n\n"
            "💡 *Dual Protection*: Combine condoms with implants or pills for total peace of mind!"
        ))

    # 8. Dual Protection
    if any(k in clean_text for k in ['dual protection', 'dual use', 'pregnancy and sti', 'double protection']):
        topic_matches.append((
            "**Dual Protection Strategy (FMoH Standard 7.2.11):**\n\n"
            "Dual protection means preventing **unintended pregnancy** and **STIs/HIV** simultaneously.\n\n"
            "### 🛡️ Implementation:\n"
            "• **The Golden Combination**: Use **Condoms** (for STI/HIV prevention) + **LARC/Hormonal Method** (Implants, IUDs, Injectables for >99% pregnancy protection).\n"
            "• **Why Essential**: Hormonal implants and IUDs do NOT protect against STIs or HIV. Condoms fill this crucial gap.\n\n"
            "💡 *Consultation*: Book a private chat with our midwives to customize your dual protection plan."
        ))

    # 9. Dysmenorrhea / Cramps
    if any(k in clean_text for k in ['cramp', 'dysmenorrhea', 'period pain', 'painful period', 'menstrual pain', 'stomach cramp', 'worh abeba pain']):
        topic_matches.append((
            "**Menstrual Cramp (Dysmenorrhea) Relief & Management:**\n\n"
            "Prostaglandin chemicals cause uterine muscle contraction during periods, leading to cramping.\n\n"
            "### 🧘 Actionable Home Steps:\n"
            "1. **Heat Therapy**: Apply a hot water bottle or heating pad to lower abdomen for 20 minutes.\n"
            "2. **Warm Hydration**: Sip warm herbal teas (ginger, chamomile) or warm water with lemon.\n"
            "3. **Magnesium & Anti-inflammatory Diet**: Eat bananas, almonds, teff, and dark leafy greens. Reduce salt and coffee.\n"
            "4. **Gentle Movement**: Light walking or yoga releases natural endorphin painkillers.\n\n"
            "⚠️ *Red Flags*: Severe pain unresponsive to painkillers or accompanied by heavy clot bleeding requires midwife evaluation."
        ))

    # 10. Heavy Bleeding
    if any(k in clean_text for k in ['heavy bleeding', 'heavy period', 'clots', 'soaking pads', 'menorrhagia', 'dem']):
        topic_matches.append((
            "**Heavy Menstrual Bleeding (Menorrhagia) Guidance:**\n\n"
            "Soaking through sanitary pads every 1–2 hours or passing large blood clots requires attention.\n\n"
            "### 📌 What You Should Do:\n"
            "1. **Track Pad Count**: Record how many pads you soak completely in 24 hours.\n"
            "2. **Prevent Anemia**: Increase iron-rich foods (beans, lentils, dark greens, eggs) and take prescribed Iron-Folic Acid (IFA) tablets.\n"
            "3. **Clinical Screening**: Heavy bleeding can stem from hormonal imbalances, uterine fibroids, or polyps.\n\n"
            "🚨 *Emergency Alert*: If you feel dizzy, faint, or soak >2 pads per hour for several consecutive hours, seek immediate clinical care!"
        ))

    # 11. Irregular Periods
    if any(k in clean_text for k in ['irregular period', 'missed period', 'late period', 'cycle length', 'pcos', 'amenorrhea', 'worh abeba']):
        topic_matches.append((
            "**Irregular Periods & Cycle Variation Guidance:**\n\n"
            "A normal menstrual cycle ranges between **21 and 35 days**. Irregular cycles can happen for several safe reasons:\n\n"
            "### 🔍 Common Causes:\n"
            "• **Adolescent Puberty**: In the first 2–3 years after menarche, hormonal feedback loops are still maturing.\n"
            "• **Stress & Weight Changes**: Physical/emotional stress, intense exercise, or sudden weight loss affect ovulation.\n"
            "• **Hormonal Conditions**: Conditions like Polycystic Ovary Syndrome (PCOS) or thyroid imbalances.\n"
            "• **Pregnancy**: A missed period in sexually active females requires a pregnancy test.\n\n"
            "💡 *Action*: Track your period start dates for 3 months and share the log with a HerWell midwife!"
        ))

    # 12. Menstrual Hygiene
    if any(k in clean_text for k in ['pad', 'hygiene', 'reusable cloth', 'sanitary', 'washing period', 'douching', 'martez']):
        topic_matches.append((
            "**Menstrual Hygiene Management (MHM) Guidelines (FMoH Section 7.1.3):**\n\n"
            "Maintaining proper menstrual hygiene prevents reproductive tract and urinary infections.\n\n"
            "### 🧼 Essential Care Rules:\n"
            "1. **Pad Changing**: Change disposable sanitary pads every **4 to 6 hours**.\n"
            "2. **Reusable Cloths**: Wash reusable cloths thoroughly with clean water and soap, and dry completely in **direct sunlight** to kill bacteria.\n"
            "3. **Genital Cleansing**: Wash vulva with clean warm water from **front to back**. Avoid internal douching or scented soaps.\n"
            "4. **Disposal**: Wrap used pads in paper or plastic before putting them in waste bins.\n\n"
            "💡 *Midwife Tip*: Reach out if you notice unusual odor, itching, or skin rashes during your period."
        ))

    # 13. Anemia & Nutrition (with Amharic terms: teff, gomen)
    if any(k in clean_text for k in ['anemia', 'iron', 'ifa', 'folic acid', 'pale', 'hemoglobin', 'weakness', 'teff', 'gomen', 'fatigue']):
        topic_matches.append((
            "**Iron-Deficiency Anemia Prevention & IFA Supplementation (FMoH Section 7.8):**\n\n"
            "Adolescent girls are vulnerable to anemia due to rapid growth and monthly menstrual blood loss.\n\n"
            "### 🍏 Key Dietary & Supplement Steps:\n"
            "1. **Daily IFA Supplements**: Take Iron & Folic Acid tablets as prescribed by healthcare workers.\n"
            "2. **Eat Iron-Rich Foods**: Consume teff, lentils, dark leafy greens (gomen), beans, eggs, and meat.\n"
            "3. **Pair with Vitamin C**: Pair iron foods with Vitamin C (oranges, lemons, tomatoes) to enhance iron absorption.\n"
            "4. **Avoid Iron Blockers**: Avoid drinking tea or coffee immediately before or after meals, as tannins block iron.\n\n"
            "💡 *Screening*: Schedule a Mid-Upper Arm Circumference (MUAC) or hemoglobin test with a midwife!"
        ))

    # 14. Food Pyramid & Exercise
    if any(k in clean_text for k in ['nutrition', 'diet', 'food pyramid', 'weight', 'bmi', 'exercise', 'growth']):
        topic_matches.append((
            "**Adolescent Growth, Food Pyramid & Physical Activity:**\n\n"
            "Adolescence provides a vital second window for physical growth and nutritional health.\n\n"
            "### 🥗 FMoH National Food Pyramid Tiers:\n"
            "1. **Tier 1 (Base - Energy Foods)**: Whole grains, teff, oats, maize, and tubers.\n"
            "2. **Tier 2 (Protective Foods)**: Fresh vegetables, leafy greens, and fruits.\n"
            "3. **Tier 3 (Body-Building)**: Pulses, beans, eggs, fish, dairy, and lean meats.\n"
            "4. **Tier 4 (Top - Smallest)**: Fats, oils, and refined sugars.\n\n"
            "### 🏃 Activity Goal:\n"
            "• Engage in at least **30 to 60 minutes of daily physical activity** (walking, sports, dancing).\n\n"
            "💡 *Tip*: Monitor your BMI-for-age periodically with a midwife to ensure healthy growth!"
        ))

    # 15. STI & Discharge
    if any(k in clean_text for k in ['sti', 'std', 'discharge', 'itching', 'sores', 'ulcer', 'syphilis', 'gonorrhea', 'chlamydia', 'burning urination']):
        topic_matches.append((
            "**Sexually Transmitted Infections (STIs) Guidance & Care:**\n\n"
            "Many STIs can occur without noticeable symptoms. Early diagnosis and full-course treatment prevent long-term complications like infertility or pelvic inflammatory disease.\n\n"
            "### 🚨 Common STI Symptoms:\n"
            "• Abnormal vaginal discharge (yellow/green, thick, or foul-smelling).\n"
            "• Burning sensation or pain during urination.\n"
            "• Genital sores, ulcers, blisters, or itching.\n"
            "• Lower abdominal or pelvic pain.\n\n"
            "### 📋 Action Plan:\n"
            "1. **Complete Full Treatment**: Take all prescribed antibiotics even if symptoms stop early.\n"
            "2. **Partner Notification**: Sexual partners must be examined and treated simultaneously to avoid re-infection.\n"
            "3. **Abstain During Treatment**: Refrain from sexual contact until both you and your partner complete treatment.\n"
            "4. **Use Condoms**: Practice dual protection with condoms to avoid future infections.\n\n"
            "💡 *Confidential Care*: STIs are common and treatable. Consult an accredited midwife confidentially on HerWell."
        ))

    # 16. HPV Vaccine
    if any(k in clean_text for k in ['hpv', 'hpv vaccine', 'cervical vaccine', 'human papillomavirus', 'gardasil', 'cervarix']):
        topic_matches.append((
            "**HPV Vaccine Guidelines & Immunization Schedule (FMoH Section 7.4.5):**\n\n"
            "HPV causes >70% of cervical cancers. The HPV vaccine is safe, free, and highly effective.\n\n"
            "### 💉 Recommended Dosing Schedule:\n"
            "• **Girls Aged 9 to 14 Years**: **2-dose schedule** (2nd dose given 6 months after the 1st dose).\n"
            "• **Females 15+ Years or Immunocompromised**: **3-dose schedule** (given at 0, 2, and 6 months).\n"
            "• Best administered before the onset of sexual activity.\n\n"
            "💡 *Location*: HPV vaccines are provided through school health programs and public health centers!"
        ))

    # 17. HIV PEP & PrEP
    if any(k in clean_text for k in ['hiv', 'aids', 'prep', 'pep', 'post-exposure', 'pre-exposure', 'retroviral']):
        topic_matches.append((
            "**HIV Prevention, PEP & PrEP Guidelines (FMoH Standards):**\n\n"
            "Combination HIV prevention strategies effectively protect against HIV transmission:\n\n"
            "### 🛡️ Key Prevention Modalities:\n"
            "1. **Post-Exposure Prophylaxis (PEP)**:\n"
            "   - Antiretroviral medication taken after potential HIV exposure (e.g. condom break, sexual assault).\n"
            "   - Must be started **within 72 hours (3 days)** of exposure and taken for 28 days.\n"
            "2. **Pre-Exposure Prophylaxis (PrEP)**:\n"
            "   - Daily pill for individuals at ongoing higher risk of HIV infection.\n"
            "3. **Condom Use & Harm Reduction**: Consistent male/female condom use reduces HIV transmission by >90%.\n\n"
            "💡 *Immediate Need*: If you suspect potential HIV exposure, visit a health facility or contact a midwife within 72 hours for PEP!"
        ))

    # 18. Pregnancy & ANC
    if any(k in clean_text for k in ['pregnan', 'trimester', 'anc', 'antenatal', 'checkup', 'pregnancy care']):
        topic_matches.append((
            "**Antenatal Care (ANC) & Pregnancy Journey (FMoH Guidelines):**\n\n"
            "Regular ANC visits safeguard the health of both mother and developing baby.\n\n"
            "### 📅 Essential ANC Steps:\n"
            "1. **Early Entry (1st Visit)**: Start ANC checkups early—ideally within the **first 12 weeks** of pregnancy.\n"
            "2. **Recommended Visits**: Attend at least **4 to 8 skilled ANC visits** throughout pregnancy.\n"
            "3. **Core Services Received**:\n"
            "   - Daily Iron-Folic Acid (IFA) supplements to prevent severe anemia.\n"
            "   - Tetanus Toxoid (TT) immunizations.\n"
            "   - Blood pressure, blood sugar, and STI/HIV screening.\n"
            "   - Individualized Birth & Complication Readiness Plan.\n\n"
            "💡 *Action*: Browse nearby accredited hospitals or schedule an online ANC consultation with a verified midwife."
        ))

    # 19. Postnatal Care & Breastfeeding
    if any(k in clean_text for k in ['breastfeed', 'lactat', 'colostrum', 'postnatal', 'postpartum', 'newborn', 'pnc']):
        topic_matches.append((
            "**Exclusive Breastfeeding & Postnatal Care Guidelines:**\n\n"
            "Breast milk provides complete nutrition, antibodies, and bonding for your growing baby.\n\n"
            "### 🍼 Recommended Breastfeeding Practices:\n"
            "1. **Early Initiation**: Put baby to the breast within **1 hour of birth**.\n"
            "2. **Feed Colostrum**: The thick yellow first milk (colostrum) is rich in protective antibodies and acts as baby's first natural vaccine. Never discard colostrum.\n"
            "3. **Exclusive Breastfeeding (0–6 Months)**: Give ONLY breast milk for the first 6 months—no water, tea, or infant formula is needed.\n"
            "4. **Postnatal Checkups**: Schedule checkups for mother and baby at 48 hours, 7 days, 6 weeks, and 6 months.\n\n"
            "💡 *Support*: If you experience nipple soreness or fever, consult a midwife promptly to check for mastitis."
        ))

    # 21. Vaginal Candidiasis / Yeast Infection
    if any(k in clean_text for k in ['yeast infection', 'thrush', 'curd discharge', 'cottage cheese discharge', 'vaginal itching', 'burning vulva', 'candidiasis']):
        topic_matches.append((
            "**Vaginal Candidiasis (Yeast Infection) Guidance:**\n\n"
            "Yeast infections are common fungal overgrowths caused by *Candida* species.\n\n"
            "### 🔬 Key Symptoms:\n"
            "• Thick, white, odorless vaginal discharge (resembling cottage cheese/curd).\n"
            "• Intense itching, redness, or burning around the vulva and vagina.\n"
            "• Soreness during urination or intercourse.\n\n"
            "### 📌 Self-Care & Treatment:\n"
            "1. **Antifungal Medication**: Treated with topical clotrimazole pessaries/creams or oral fluconazole as prescribed.\n"
            "2. **Hygiene Habit**: Wear breathable cotton underwear. Avoid tight synthetic pants, scented soaps, or internal douching.\n"
            "3. **Complete Course**: Finish full prescribed treatment even if symptoms improve early.\n\n"
            "💡 *Midwife Consultation*: Schedule an evaluation to confirm diagnosis and get proper antifungal treatment."
        ))

    # 22. Bacterial Vaginosis (BV)
    if any(k in clean_text for k in ['bacterial vaginosis', 'bv', 'fishy odor', 'fishy smell', 'thin grey discharge', 'watery discharge']):
        topic_matches.append((
            "**Bacterial Vaginosis (BV) Self-Care & Care Guidelines:**\n\n"
            "Bacterial Vaginosis occurs when natural vaginal bacterial flora (lactobacilli) balance is altered.\n\n"
            "### 🔬 Key Symptoms:\n"
            "• Thin, watery, greyish-white vaginal discharge.\n"
            "• Distinctive **strong 'fishy' odor**, especially noticeable after bathing or intercourse.\n"
            "• Mild genital discomfort (itching is usually absent or minimal compared to yeast infections).\n\n"
            "### 📋 Management Plan:\n"
            "1. **Antibiotic Treatment**: Treated effectively with oral or vaginal Metronidazole/Clindamycin prescribed by health workers.\n"
            "2. **Avoid Douching**: Never douche or use harsh soaps; douching worsens BV by washing away good bacteria.\n"
            "3. **Avoid Scented Products**: Use plain warm water for daily external washing.\n\n"
            "💡 *Midwife Care*: Book a consultation for confidential diagnosis and antibiotic prescription."
        ))

    # 23. Urinary Tract Infection (UTI)
    if any(k in clean_text for k in ['uti', 'urinary infection', 'painful urination', 'frequent urination', 'cloudy urine', 'pee pain', 'burning urine']):
        topic_matches.append((
            "**Urinary Tract Infection (UTI) Guidance & Prevention:**\n\n"
            "UTIs occur when bacteria enter the urethra and bladder, causing localized inflammation.\n\n"
            "### 🚨 Classic Symptoms:\n"
            "• Sharp burning or pain during urination (dysuria).\n"
            "• Persistent, urgent need to urinate frequently, passing small amounts.\n"
            "• Cloudy, dark, or strong-smelling urine.\n"
            "• Lower pelvic pressure or discomfort.\n\n"
            "### 💧 Actionable Steps:\n"
            "1. **Increase Water Intake**: Drink 2 to 3 liters of clean water daily to flush bacteria from the bladder.\n"
            "2. **Wipe Front to Back**: Always wipe from front to back after using the toilet.\n"
            "3. **Urinate After Intercourse**: Helps flush away any introduced bacteria.\n"
            "4. **Antibiotics Needed**: Requires a short course of oral antibiotics prescribed by a midwife or clinician.\n\n"
            "⚠️ *Warning*: If accompanied by high fever, back pain, or nausea, seek urgent medical care to rule out kidney infection!"
        ))

    # 24. Premenstrual Syndrome (PMS) & PMDD
    if any(k in clean_text for k in ['pms', 'pmdd', 'premenstrual', 'bloating before period', 'tender breasts', 'mood swings period']):
        topic_matches.append((
            "**Premenstrual Syndrome (PMS) & PMDD Self-Care:**\n\n"
            "PMS involves physical and emotional changes occurring 1 to 2 weeks before menstruation due to hormonal fluctuations.\n\n"
            "### 🌸 Symptom Relief Strategies:\n"
            "1. **Dietary Adjustments**: Reduce salt (lowers bloating), caffeine, and refined sugars. Eat complex carbs (teff, oats) and foods high in Calcium and Vitamin B6.\n"
            "2. **Physical Exercise**: 30 minutes of aerobic exercise (walking, jogging, dancing) boosts serotonin and mood.\n"
            "3. **Stress Relief**: Practice deep breathing, adequate sleep (7–8 hours), and warm baths.\n"
            "4. **PMDD (Severe Form)**: If mood swings cause severe depression or anxiety disabling daily life, consult a healthcare provider for medical support.\n\n"
            "💡 *Tip*: Log your symptoms in a monthly mood and cycle tracker!"
        ))

    # 25. First Period / Menarche (Girls 10-14 Years)
    if any(k in clean_text for k in ['first period', 'menarche', 'puberty girl', 'starting period', 'young girl period']):
        topic_matches.append((
            "**First Period (Menarche) Guide for Adolescent Girls & Parents:**\n\n"
            "Menarche is a healthy, natural milestone marking the onset of female reproductive maturity, typically occurring between ages 10 and 15.\n\n"
            "### 🌸 Essential Guidance for Young Girls:\n"
            "1. **Normal Expectation**: Blood flow may start as light brown spotting or red bleeding lasting 3 to 7 days.\n"
            "2. **Cycle Irregularity**: Periods are often unpredictable or irregular in the first 2 years as your body's hormone levels settle.\n"
            "3. **Preparedness Pack**: Keep 2 clean sanitary pads and a spare underwear in your school bag at all times.\n"
            "4. **Pain Relief**: Mild cramps are normal and can be eased with a warm water bottle or light resting.\n\n"
            "💡 *Confidential Support*: You are not alone! Reach out to a verified HerWell midwife to ask any private body questions."
        ))

    # 26. Tampons, Menstrual Cups & TSS Safety
    if any(k in clean_text for k in ['tampon', 'menstrual cup', 'tss', 'toxic shock', 'inserting pad']):
        topic_matches.append((
            "**Tampon & Menstrual Cup Safety Guidelines (TSS Prevention):**\n\n"
            "Internal menstrual products provide convenience and comfort when used with strict hygiene practices.\n\n"
            "### 🧼 Usage Rules:\n"
            "1. **Tampon Changing Schedule**: Change tampons every **4 to 8 hours max**. Never leave a tampon in for longer than 8 hours.\n"
            "2. **Menstrual Cup Sterilization**: Boil medical-grade silicone cups in boiling water for 5–10 minutes before each cycle. Empty and wash every 8 to 12 hours.\n"
            "3. **Toxic Shock Syndrome (TSS) Awareness**: TSS is a rare, serious bacterial infection linked to prolonged tampon use.\n"
            "   - *TSS Red Flags*: Sudden high fever, rash, dizziness, fainting, vomiting.\n"
            "   - *Action*: Remove tampon immediately and seek emergency hospital care if these occur.\n\n"
            "💡 *Hygiene First*: Always wash hands thoroughly with soap before inserting or removing any product."
        ))

    # 27. Contraceptive Side Effects: Spotting & Bleeding
    if any(k in clean_text for k in ['spotting', 'breakthrough bleeding', 'light bleeding pill', 'implant bleeding', 'side effect bleeding']):
        topic_matches.append((
            "**Contraceptive Side Effect: Spotting & Irregular Bleeding:**\n\n"
            "Unscheduled light bleeding or brown spotting is the most common, non-dangerous side effect when starting new hormonal birth control.\n\n"
            "### 📌 Clinical Timeline & Guidance:\n"
            "1. **First 3 to 6 Months**: Common with Implants (Implanon/Jadelle), Depo-Provera, and low-dose OCPs as the uterine lining adapts.\n"
            "2. **Is It Dangerous?**: No. Spotting does **NOT** reduce the pregnancy protection of your method as long as you take pills on time or keep your implant in place.\n"
            "3. **Management**: Reassurance is key. If spotting persists beyond 6 months or becomes very heavy, consult a midwife.\n\n"
            "💡 *Midwife Consultation*: Book a chat to review side effect management options."
        ))

    # 28. Contraceptive Side Effects: Nausea & Weight Myths
    if any(k in clean_text for k in ['pill nausea', 'birth control weight', 'gaining weight pill', 'contraceptive myth', 'contraceptive nausea']):
        topic_matches.append((
            "**Managing Pill Nausea & Contraceptive Weight Myths:**\n\n"
            "Understanding common mild side effects helps you stay consistent with birth control.\n\n"
            "### 💊 Managing Pill Nausea:\n"
            "• Take daily oral pills **with a meal** or **right before bedtime** to avoid stomach irritation.\n"
            "• Nausea usually subsides completely after the first 2 to 4 weeks.\n\n"
            "### ⚖️ Weight Gain Myths vs Facts:\n"
            "• Scientific evidence shows birth control pills and implants do **NOT** cause direct fat gain.\n"
            "• Depo-Provera injectables may cause minor fluid retention or increased appetite in some women, which can be managed with healthy eating and exercise.\n\n"
            "💡 *Questions?*: Speak with a HerWell midwife for individualized contraceptive counseling."
        ))

    # 29. First Trimester Pregnancy Care (0-12 Weeks)
    if any(k in clean_text for k in ['first trimester', 'early pregnancy', 'morning sickness', 'folic acid pregnancy', '1st trimester']):
        topic_matches.append((
            "**First Trimester Pregnancy Guidance (0–12 Weeks):**\n\n"
            "The first trimester is the foundational period for fetal organ development.\n\n"
            "### 🤰 Essential First Steps:\n"
            "1. **Start Daily Folic Acid**: Take 400 mcg Folic Acid daily to prevent neural tube birth defects.\n"
            "2. **First ANC Visit**: Schedule your 1st Antenatal Care checkup before 12 weeks for ultrasound and blood tests.\n"
            "3. **Manage Morning Sickness**: Eat small, frequent dry meals (crackers, toast, teff). Sip ginger tea. Avoid greasy foods.\n"
            "4. **Avoid Harmful Substances**: Avoid alcohol, smoking, unnecessary medications, and unpasteurized milk.\n\n"
            "🚨 *Red Flag*: Any vaginal bleeding or severe lower abdominal cramping requires urgent medical evaluation!"
        ))

    # 30. Second Trimester Pregnancy Care (13-27 Weeks)
    if any(k in clean_text for k in ['second trimester', '2nd trimester', 'baby movement', 'quickening', 'muac pregnancy']):
        topic_matches.append((
            "**Second Trimester Pregnancy Guidance (13–27 Weeks):**\n\n"
            "Often called the 'golden trimester', energy returns and morning sickness usually fades.\n\n"
            "### 🌟 Key Milestones & Care:\n"
            "1. **Fetal Movement (Quickening)**: First subtle flutters usually felt between **18 and 22 weeks** (earlier in second pregnancies).\n"
            "2. **Anemia & MUAC Screening**: Continue daily Iron-Folic Acid (IFA) supplements. Check Mid-Upper Arm Circumference (MUAC) for maternal nutrition.\n"
            "3. **Tetanus Toxoid (TT)**: Receive required TT vaccine doses during ANC visits.\n"
            "4. **Anomaly Ultrasound**: Recommended around 20 weeks to check baby's physical development.\n\n"
            "💡 *Midwife ANC*: Book an online pregnancy progress checkup with a verified midwife!"
        ))

    # 31. Third Trimester Care & Labor Warning Signs (28-40 Weeks)
    if any(k in clean_text for k in ['third trimester', '3rd trimester', 'labor signs', 'contractions', 'water broke', 'hospital bag']):
        topic_matches.append((
            "**Third Trimester & Labor Readiness Guidance (28–40 Weeks):**\n\n"
            "Final preparations for safe delivery and baby arrival.\n\n"
            "### 🎒 Delivery & Labor Preparedness:\n"
            "1. **Individual Birth Plan**: Identify your health facility, transport plan, emergency savings, and blood donor contact.\n"
            "2. **Kick Counting**: Monitor fetal kicks daily—you should feel at least 10 movements over 2 hours while resting.\n"
            "3. **True Labor Signs**:\n"
            "   - Regular, increasingly strong contractions coming closer together.\n"
            "   - Gush or trickle of clear fluid from vagina (water breaking / rupture of membranes).\n"
            "   - Pinkish mucus discharge ('bloody show').\n\n"
            "🚨 *Immediate Action*: Go straight to the delivery health facility when true labor signs begin!"
        ))

    # 32. Postpartum Bleeding (Lochia) & Hemorrhage Signs
    if any(k in clean_text for k in ['lochia', 'postpartum bleeding', 'bleeding after birth', 'after delivery bleeding']):
        topic_matches.append((
            "**Postpartum Bleeding (Lochia) vs Warning Signs:**\n\n"
            "Vaginal discharge after delivery (Lochia) progresses naturally through 3 stages over 4 to 6 weeks.\n\n"
            "### 🩸 Normal Lochia Stages:\n"
            "1. **Lochia Rubra (Days 1–4)**: Heavy, dark red blood with small clots.\n"
            "2. **Lochia Serosa (Days 4–10)**: Thinner, pinkish-brown discharge.\n"
            "3. **Lochia Alba (Days 10–28)**: Yellowish-white creamy discharge.\n\n"
            "🚨 *Postpartum Hemorrhage Alert*: Soaking >1 pad per hour, passing large egg-sized clots, foul-smelling discharge, high fever, or feeling faint requires immediate emergency clinical care!"
        ))

    # 33. Postpartum Depression & Emotional Wellbeing
    if any(k in clean_text for k in ['postpartum depression', 'ppd', 'baby blues', 'crying after baby', 'postnatal anxiety']):
        topic_matches.append((
            "**Postpartum Depression (PPD) & Maternal Mental Health:**\n\n"
            "Emotional fluctuations after childbirth are real, common, and treatable.\n\n"
            "### 🧠 Understanding the Difference:\n"
            "1. **Baby Blues (Days 3–10)**: Mild sadness, crying spells, and anxiety due to rapid hormone drops; resolves naturally within 2 weeks.\n"
            "2. **Postpartum Depression (PPD)**: Severe sadness, anxiety, detachment from baby, or feeling overwhelmed lasting longer than 2 weeks.\n\n"
            "### 💗 Support Actions:\n"
            "• **Speak Up**: Share your feelings with your partner, family, or midwife without shame.\n"
            "• **Rest & Help**: Accept help with household chores and rest whenever baby sleeps.\n"
            "• **Professional Care**: PPD responds very well to counseling and supportive healthcare.\n\n"
            "💡 *HerWell Care*: Book a compassionate, private consultation with a midwife for postpartum support."
        ))

    # 34. Newborn Umbilical Cord Care & Infection (Omphalitis)
    if any(k in clean_text for k in ['umbilical cord', 'cord care', 'baby navel', 'omphalitis', 'newborn belly button']):
        topic_matches.append((
            "**Newborn Umbilical Cord Care & Omphalitis Prevention:**\n\n"
            "Proper care allows the newborn umbilical cord stump to dry and fall off naturally within 7 to 14 days.\n\n"
            "### 🍼 Essential Care Rules:\n"
            "1. **Keep Clean & Dry**: Expose cord stump to air. Fold diaper down below the stump so urine does not soak it.\n"
            "2. **Chlorhexidine Application**: Apply 7.1% Chlorhexidine gel (if provided by health facility) as directed.\n"
            "3. **Do NOT Apply Harmful Substances**: Never apply cow dung, butter, ash, or unsterilized oils to the cord.\n\n"
            "🚨 *Infection Signs (Omphalitis)*: Redness around belly button skin, pus/foul discharge, swelling, or baby fever. Seek immediate newborn clinic care!"
        ))

    # 35. Adolescent Minor Confidentiality & Rights (FMoH Policy)
    if any(k in clean_text for k in ['confidentiality', 'minor consent', 'under 18 rights', 'parental consent', 'youth rights']):
        topic_matches.append((
            "**Adolescent Reproductive Rights & Confidentiality (FMoH Policy):**\n\n"
            "Ethiopian Ministry of Health (FMoH) Guidelines guarantee youth-friendly, confidential reproductive healthcare.\n\n"
            "### 📜 Key Legal & Clinical Rights:\n"
            "1. **Mature Minor Consent (Ages 15+)**: Adolescents aged 15 and above can independently access confidential STI screening, HIV testing/CHTC, and reproductive health counseling.\n"
            "2. **Strict Privacy**: Healthcare workers cannot disclose your health information to parents or third parties without your voluntary consent.\n"
            "3. **Non-Judgmental Service**: Right to respectful, stigma-free counseling regardless of marital status.\n\n"
            "💡 *HerWell AI*: Your interactions on HerWell are confidential and secure."
        ))

    # 36. Fertility Window & Ovulation Tracking
    if any(k in clean_text for k in ['ovulation', 'fertile window', 'cervical mucus', 'getting pregnant', 'conception calculator']):
        topic_matches.append((
            "**Understanding Ovulation & The Fertile Window:**\n\n"
            "Tracking your fertile window helps plan pregnancy or practice natural cycle awareness.\n\n"
            "### 🗓️ Key Clinical Facts:\n"
            "1. **Timing**: Ovulation occurs approximately **14 days before** your next expected period.\n"
            "2. **Fertile Window**: 5 days before ovulation plus the day of ovulation (sperm can survive up to 5 days in cervical mucus).\n"
            "3. **Body Signs**: Stretchy, clear, egg-white cervical mucus and a slight increase in basal body temperature.\n\n"
            "💡 *Plan Ahead*: Consult a HerWell midwife for personalized preconception counseling!"
        ))

    # 37. Cervical Cancer Screening (VIA & Pap Smear)
    if any(k in clean_text for k in ['cervical screening', 'pap smear', 'via test', 'cervical cancer test']):
        topic_matches.append((
            "**Cervical Cancer Screening Guidelines (FMoH Section 7.4):**\n\n"
            "Cervical cancer is preventable through regular screening and early treatment of precancerous lesions.\n\n"
            "### 🔬 Recommended Screening Protocols:\n"
            "1. **Screening Target**: All women aged **30 to 49 years** (or starting earlier from 25 for HIV-positive women).\n"
            "2. **Primary Method (VIA)**: Visual Inspection with Acetic Acid (VIA) is quick, painless, and provides immediate single-visit results.\n"
            "3. **Screening Frequency**: Every **3 to 5 years** if results are normal.\n\n"
            "💡 *Facility Access*: VIA screening is available at government health centers and primary hospitals!"
        ))

    # If we have matches, combine up to 2 top matches for multi-topic queries!
    if topic_matches:
        if len(topic_matches) == 1:
            return f"🌸 **{greeting}HerWell AI Guidance**\n\n" + topic_matches[0]
        else:
            # Multi-topic combination!
            combined = f"🌸 **{greeting}HerWell Multi-Topic Health Guidance**\n\n"
            combined += "Based on your query, here is relevant guidance across your matching health areas:\n\n"
            combined += "\n\n---\n\n".join([m for m in topic_matches[:2]])
            return combined

    # Advanced Premium Fallback Response
    else:
        role_header = "🩺 **Healthcare Worker & Provider Guidance**\n\n" if is_midwife else "🌸 **HerWell Reproductive & Women's Health Education**\n\n"
        return (
            f"{role_header}"
            f"{greeting}Thank you for reaching out regarding: *'{question_text.strip()}'*.\n\n"
            "HerWell AI is engineered to provide trusted, evidence-based reproductive health guidance grounded in the official **Ethiopian Ministry of Health (FMoH 2022)** Technical Guidelines.\n\n"
            "### 📋 How to Get the Most Accurate Guidance:\n"
            "To help me give you the best information, try asking about specific topics such as:\n"
            "1. **Menstrual Wellbeing**: *\"How do I manage severe period pain at home?\"*\n"
            "2. **Family Planning & Contraception**: *\"What is the difference between Implants and IUDs?\"*\n"
            "3. **Nutrition & Anemia**: *\"What iron-rich foods help prevent anemia?\"*\n"
            "4. **Pregnancy & ANC**: *\"What are warning signs during pregnancy?\"*\n"
            "5. **STI & HPV Protection**: *\"What is the HPV vaccine schedule for girls?\"*\n\n"
            "### 🩺 Connect with a Verified Midwife:\n"
            "For personalized medical evaluation, diagnosis, physical checkups, or prescription services, you can schedule a private, confidential audio/video consultation with an approved midwife directly in the app.\n\n"
            "⚠️ *Educational Disclaimer: Information provided is for general guidance only and does not constitute a formal clinical diagnosis.*"
        )


class AIQuestionViewSet(viewsets.ModelViewSet):
    """
    AI Health Assistant Module (Floating AI Assistant).
    Provides conversational reproductive and maternal health guidance, AI safety checks,
    suggested questions, and feedback mechanisms.
    """

    queryset = AIQuestion.objects.all()
    serializer_class = AIQuestionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return AIQuestion.objects.filter(user=self.request.user).order_by('-created_at')

    def perform_create(self, serializer):
        question_text = serializer.validated_data.get('question', '')
        ai_response = _generate_ai_health_response(question_text, user=self.request.user)
        serializer.save(user=self.request.user, response=ai_response)

    @extend_schema(summary="Ask floating AI Health Assistant a question", tags=["AI Assistant"])
    @action(detail=False, methods=['post'])
    def ask(self, request):
        question_text = request.data.get('question')
        if not question_text:
            return Response({'error': 'Question text is required.'}, status=status.HTTP_400_BAD_REQUEST)

        ai_response = _generate_ai_health_response(question_text, user=request.user)
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
        # 1. Quick Horizontal Chip Labels for Adolescent Mobile UI
        popular_chips = [
            "🌸 Period Cramp Relief at School",
            "🍏 Teff & Iron for Anemia",
            "🛡️ Youth Dual Protection",
            "📜 Confidentiality Rights (15+)",
        ]

        # 2. Lean Prompts Tailored for Adolescent Girls
        flat_prompts = [
            "How do I manage severe period pain safely at school and home?",
            "What iron-rich Ethiopian foods (teff, gomen) prevent anemia in growing girls?",
            "What is 'Dual Protection' and why is it essential for STI/HIV & pregnancy prevention?",
            "What confidential health rights do adolescent girls (15+) have under FMoH guidelines?",
        ]

        # 3. Adolescent SRH Core Categories
        categorized_questions = {
            "🌸 Puberty, Period & Body Care": [
                "How do I manage period pain safely at school and home?",
                "What should I know about my first period (menarche) and body changes?"
            ],
            "🍏 Adolescent Nutrition & Growth": [
                "What iron-rich Ethiopian foods (teff, gomen) prevent anemia?",
                "Why are Iron-Folic Acid (IFA) supplements vital during teenage growth?"
            ],
            "🛡️ Youth Protection & Confidential Rights": [
                "What is 'Dual Protection' and why is it essential for youth?",
                "What confidential health rights do adolescents (15+) have under Ethiopian law?"
            ]
        }

        return Response({
            'count': len(flat_prompts),
            'popular_chips': popular_chips,
            'suggested_questions': flat_prompts,
            'categories': categorized_questions,
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


class AIChatThrottle(UserRateThrottle):
    scope = 'ai_chat'
    rate = '20/minute'


class AIChatView(APIView):
    """
    POST /api/v1/ai/chat/
    Conversational AI Assistant endpoint for Phase 1.
    Integrates Safety Triage, Knowledge Base Retrieval, and Conversation Persistence.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_classes = [AIChatThrottle]

    @extend_schema(
        request=AIChatRequestSerializer,
        responses={200: AIChatResponseSerializer},
        summary="Send message to AI Assistant Chat",
        tags=["AI Assistant Chat"]
    )
    def post(self, request):
        serializer = AIChatRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        message_text = serializer.validated_data['message']
        conversation_id = serializer.validated_data.get('conversation_id')
        language = serializer.validated_data.get('language', 'en')

        service = AIAssistantService()
        result = service.process_chat_message(
            user=request.user,
            message_text=message_text,
            conversation_id=str(conversation_id) if conversation_id else None,
            language=language
        )

        return Response(result, status=status.HTTP_200_OK)


class AIConversationViewSet(viewsets.ModelViewSet):
    """
    GET /api/v1/ai/conversations/
    DELETE /api/v1/ai/conversations/{id}/
    List and delete user conversation history.
    """
    serializer_class = AIConversationSerializer
    permission_classes = [permissions.IsAuthenticated]
    http_method_names = ['get', 'delete']

    def get_queryset(self):
        return AIConversation.objects.filter(user=self.request.user).order_by('-updated_at')

