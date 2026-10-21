from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django.contrib.auth import get_user_model
from apps.learning.models import Category, Topic, Article

User = get_user_model()


class Command(BaseCommand):
    help = "Seed initial Figma Learning Center categories, topics, and sample articles"

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding Figma Learning Center modules...")

        admin_user, _ = User.objects.get_or_create(
            username="editorial_team",
            defaults={
                "email": "editor@herwell.org",
                "role": "ADMIN",
                "first_name": "HerWell",
                "last_name": "Editorial Team",
            }
        )

        categories_data = [
            {
                "name": "Adolescent Girls Health & Nutrition",
                "subtitle_summary": "Puberty, menstrual health, nutrition & healthy lifestyle, mental & well-being",
                "icon": "sparkles",
                "order": 1,
                "topics": [
                    "Puberty",
                    "Menstruation",
                    "Nutrition & healthy lifestyle",
                    "Healthy Relationships",
                    "Consent",
                    "Reproductive Rights",
                ],
            },
            {
                "name": "Reproductive Health & Care",
                "subtitle_summary": "Pregnancy prevention, maternal care, ANC, newborn care, and checkups",
                "icon": "heart-pulse",
                "order": 2,
                "topics": [
                    "Pregnancy Prevention and Testing",
                    "Antenatal Care (ANC)",
                    "Childbirth",
                    "Postnatal Care",
                    "Post-Abortion Care",
                    "Reproductive Health Treatment",
                ],
            },
            {
                "name": "Psychosocial Support & Protection",
                "subtitle_summary": "Mental health, GBV support, counseling services, and emergency help",
                "icon": "shield-check",
                "order": 3,
                "topics": [
                    "Gender-Based Violence (GBV)",
                    "Support & Response Services",
                    "Mental Health Counseling",
                    "Referral Services",
                    "Safeguarding",
                    "Adolescent-Friendly Support",
                ],
            },
            {
                "name": "Prevention and Awareness",
                "subtitle_summary": "STI/HIV prevention, HPV & cervical cancer awareness, healthy relationships",
                "icon": "activity",
                "order": 4,
                "topics": [
                    "Contraceptive Counseling",
                    "Family Planning Services",
                    "HIV Prevention",
                    "STI Prevention",
                    "HPV Vaccination",
                    "Health Promotion",
                ],
            },
        ]

        for cat_item in categories_data:
            cat_obj, created = Category.objects.get_or_create(
                name=cat_item["name"],
                defaults={
                    "slug": slugify(cat_item["name"]),
                    "subtitle_summary": cat_item["subtitle_summary"],
                    "icon": cat_item["icon"],
                    "order": cat_item["order"],
                }
            )

            for order_idx, topic_name in enumerate(cat_item["topics"], start=1):
                Topic.objects.get_or_create(
                    category=cat_obj,
                    name=topic_name,
                    defaults={
                        "slug": slugify(topic_name),
                        "order": order_idx,
                    }
                )

        articles_data = [
            {
                "topic_name": "Puberty",
                "title": "What is Puberty?",
                "summary": "Puberty is a natural part of growing up. Learn about physical and emotional changes.",
                "content": (
                    "Puberty is a natural part of growing up. It is the time when your body begins to change "
                    "from a child's body into an adult's body.\n\n"
                    "For most girls, it usually begins between 8 and 13 years of age, but everyone grows at "
                    "their own pace. During puberty, you may notice changes such as breast development, a growth spurt, "
                    "body hair, and your first menstrual period.\n\n"
                    "You may also experience new emotions and mood changes because your hormones are developing. "
                    "These changes are normal and are a healthy part of becoming an adult."
                ),
                "cover_image": "https://images.unsplash.com/photo-1544005313-94ddf0286df2?w=800",
                "content_type": "TEXT",
                "reading_time_minutes": 3,
                "sections": [
                    {"title": "Breast development", "detail": "Small swellings (breast buds) form under the nipples."},
                    {"title": "Growing taller", "detail": "A noticeable growth spurt in height and body shape changes."},
                    {"title": "First menstrual period", "detail": "The start of regular or irregular monthly bleeding (menarche)."},
                    {"title": "Body hair growth", "detail": "Soft hair starts growing under arms and in the pubic area."},
                    {"title": "Emotional and mood changes", "detail": "Fluctuations in feelings caused by developing hormones."},
                ],
                "key_takeaway_tip": "Remember: Every girl grows differently. Your body develops at its own pace, and that's completely normal.",
            },
            {
                "topic_name": "Menstruation",
                "title": "Menstruation & Menstrual Hygiene Guide",
                "summary": "Understanding your menstrual cycle, hygiene practices, and tracking your period.",
                "content": (
                    "Menstruation is a normal biological process where the body sheds the lining of the uterus every month. "
                    "A typical cycle lasts between 21 and 35 days, with bleeding lasting between 3 to 7 days.\n\n"
                    "Maintaining proper hygiene during your period is essential for preventing infections. Always wash hands "
                    "before and after changing sanitary products, change pads every 4 to 6 hours, and dispose of used pads safely."
                ),
                "cover_image": "https://images.unsplash.com/photo-1516549655169-df83a0774514?w=800",
                "content_type": "TEXT",
                "reading_time_minutes": 4,
                "sections": [
                    {"title": "Cycle Length & Phases", "detail": "Most cycles range between 21-35 days from day one of bleeding."},
                    {"title": "Hygiene Practices", "detail": "Change sanitary pads every 4-6 hours and wash with clean water."},
                    {"title": "Cramp Management", "detail": "Gentle exercise, warm compresses, and hydration help relieve cramps."},
                ],
                "key_takeaway_tip": "Track your start dates each month on a calendar or in HerWell to know your cycle pattern.",
            },
            {
                "topic_name": "Nutrition & healthy lifestyle",
                "title": "Adolescent Nutrition & Anemia Prevention",
                "summary": "Essential foods, iron-rich nutrition, and hydration for growing adolescent girls.",
                "content": (
                    "Adolescence is a period of rapid growth and development. Eating a balanced diet rich in iron, calcium, "
                    "and proteins ensures proper physical development and prevents nutritional deficiencies like anemia.\n\n"
                    "Iron-rich foods like dark green vegetables, beans, lentils, eggs, and lean meats help replenish blood lost "
                    "during menstruation. Pairing iron with vitamin C foods (oranges, tomatoes) enhances iron absorption."
                ),
                "cover_image": "https://images.unsplash.com/photo-1490645935967-10de6ba17061?w=800",
                "content_type": "TEXT",
                "reading_time_minutes": 3,
                "sections": [
                    {"title": "Iron-Rich Foods", "detail": "Lentils, beans, spinach, and eggs help maintain healthy hemoglobin levels."},
                    {"title": "Bone Health with Calcium", "detail": "Dairy, fortified foods, and sesame seeds strengthen growing bones."},
                    {"title": "Hydration Needs", "detail": "Drink at least 6-8 glasses of clean water daily."},
                ],
                "key_takeaway_tip": "Avoid drinking strong tea or coffee immediately after meals, as tannins reduce iron absorption.",
            },
            {
                "topic_name": "Antenatal Care (ANC)",
                "title": "Antenatal Care (ANC): Why Early Visits Matter",
                "summary": "Key milestones, schedule of visits, and health checks during pregnancy.",
                "content": (
                    "Antenatal Care (ANC) is the routine healthcare provided to pregnant mothers by skilled midwives or doctors. "
                    "Starting ANC visits in the first trimester ensures maternal safety and healthy fetal development.\n\n"
                    "WHO recommends at least 8 contacts during pregnancy. These visits include ultrasound scans, blood pressure "
                    "checks, iron and folic acid supplementation, and birth preparedness planning."
                ),
                "cover_image": "https://images.unsplash.com/photo-1584515979956-d9f6e5d09982?w=800",
                "content_type": "TEXT",
                "reading_time_minutes": 5,
                "sections": [
                    {"title": "First Trimester Checkup", "detail": "Confirms pregnancy, estimates due date, and checks maternal health."},
                    {"title": "Screening Tests", "detail": "Blood tests, urine tests, and ultrasounds monitor fetal growth."},
                    {"title": "Danger Signs", "detail": "Severe headache, bleeding, swelling, or vision changes require urgent care."},
                ],
                "key_takeaway_tip": "Attend all scheduled midwife visits even if you feel completely healthy.",
            },
            {
                "topic_name": "Pregnancy Prevention and Testing",
                "title": "Understanding Contraceptive Methods & Emergency Options",
                "summary": "Safe, confidential reproductive healthcare and understanding your options.",
                "content": (
                    "Adolescents have the right to confidential, accurate information on reproductive health and family planning. "
                    "Modern contraceptive methods include barrier methods (male and female condoms), hormonal methods (pills, injections, implants), "
                    "and emergency contraception.\n\n"
                    "Condoms provide dual protection: preventing both unintended pregnancy and sexually transmitted infections (STIs)."
                ),
                "cover_image": "https://images.unsplash.com/photo-1576091160399-112ba8d25d1d?w=800",
                "content_type": "TEXT",
                "reading_time_minutes": 4,
                "sections": [
                    {"title": "Dual Protection", "detail": "Condoms are the only method that also prevents STIs and HIV."},
                    {"title": "Emergency Contraception", "detail": "Most effective when taken within 72 hours of unprotected intercourse."},
                    {"title": "Midwife Counseling", "detail": "A certified midwife can help you choose the best method for your body."},
                ],
                "key_takeaway_tip": "Consult a healthcare professional or midwife on HerWell for private, confidential guidance.",
            },
            {
                "topic_name": "Mental Health Counseling",
                "title": "Mental Well-Being & Managing Academic/Social Stress",
                "summary": "Coping mechanisms for anxiety, emotional balance, and seeking counseling support.",
                "content": (
                    "Adolescence brings emotional changes, social pressures, and academic stress. Taking care of your mental health "
                    "is just as important as caring for your physical health.\n\n"
                    "Practicing deep breathing, talking to trusted mentors, maintaining regular sleep habits, and seeking confidential "
                    "counseling are positive ways to build resilience and navigate challenging times."
                ),
                "cover_image": "https://images.unsplash.com/photo-1506126613408-eca07ce68773?w=800",
                "content_type": "TEXT",
                "reading_time_minutes": 4,
                "sections": [
                    {"title": "Signs of Stress", "detail": "Difficulty sleeping, persistent worry, and changes in appetite."},
                    {"title": "Self-Care Routines", "detail": "Regular sleep, balanced meals, physical activity, and mindfulness."},
                    {"title": "When to Reach Out", "detail": "If feelings of sadness or anxiety persist for more than two weeks, talk to a counselor."},
                ],
                "key_takeaway_tip": "You are never alone. HerWell provides direct, confidential connections to certified support counselors.",
            },
            {
                "topic_name": "Gender-Based Violence (GBV)",
                "title": "Safe Spaces: Recognizing GBV & Accessing Protection",
                "summary": "Rights, safety protocols, confidential reporting, and emergency hotline lines.",
                "content": (
                    "Gender-Based Violence (GBV) includes any harm perpetrated against a person's will based on gender. "
                    "Every girl and woman has the fundamental right to safety, bodily autonomy, and dignity.\n\n"
                    "If you or someone you know experiences harassment, domestic violence, or assault, immediate medical care "
                    "(within 72 hours) and psychological support are critical. Emergency lines and confidential hotlines are available 24/7."
                ),
                "cover_image": "https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?w=800",
                "content_type": "TEXT",
                "reading_time_minutes": 5,
                "sections": [
                    {"title": "Types of GBV", "detail": "Physical, emotional, verbal, and digital harassment or violence."},
                    {"title": "72-Hour Medical Window", "detail": "Immediate medical attention provides emergency prophylaxis and care."},
                    {"title": "Emergency Support Lines", "detail": "Direct emergency lines (8044, 911) can be reached right inside HerWell."},
                ],
                "key_takeaway_tip": "Your safety is paramount. Use the SOS button or Hotline tab in HerWell for instant emergency help.",
            },
            {
                "topic_name": "STI Prevention",
                "title": "STI Symptoms, Prevention & Getting Tested",
                "summary": "Common signs, prevention strategies, and confidential clinical screening.",
                "content": (
                    "Sexually Transmitted Infections (STIs) are infections transmitted through sexual contact. Many STIs show no early symptoms, "
                    "which is why routine screening and prevention are essential.\n\n"
                    "Common symptoms can include unusual discharge, pelvic pain, burning during urination, or sores. Most STIs are curable "
                    "with early antibiotics or manageable with antiviral therapy."
                ),
                "cover_image": "https://images.unsplash.com/photo-1579684385127-1ef15d508118?w=800",
                "content_type": "TEXT",
                "reading_time_minutes": 4,
                "sections": [
                    {"title": "Prevention", "detail": "Consistent and correct use of condoms is the most effective barrier."},
                    {"title": "Screening", "detail": "Regular STI tests at nearby youth-friendly clinics protect your future health."},
                    {"title": "Partner Treatment", "detail": "Both partners must be treated simultaneously to avoid reinfection."},
                ],
                "key_takeaway_tip": "Never feel ashamed to ask a healthcare provider or HerWell midwife about STI screening.",
            },
            {
                "topic_name": "HPV Vaccination",
                "title": "HPV Vaccine: Protecting Your Future Cervical Health",
                "summary": "Understanding HPV, vaccination schedules, and cervical cancer prevention.",
                "content": (
                    "Human Papillomavirus (HPV) is a common virus that can lead to cervical cancer in later years. The HPV vaccine is safe, "
                    "highly effective, and recommended by WHO and the Ministry of Health for girls aged 9 to 14.\n\n"
                    "Receiving the vaccine before exposure provides strong, long-lasting immunity against the high-risk HPV strains that cause "
                    "the vast majority of cervical cancers."
                ),
                "cover_image": "https://images.unsplash.com/photo-1632053001859-99413ca2c355?w=800",
                "content_type": "TEXT",
                "reading_time_minutes": 3,
                "sections": [
                    {"title": "Who Should Get Vaccinated", "detail": "Adolescent girls aged 9-14 through school and health facility campaigns."},
                    {"title": "Vaccine Safety", "detail": "Endorsed globally by WHO with millions of safe doses administered worldwide."},
                    {"title": "Cervical Screening", "detail": "Routine screening in adulthood continues to provide secondary protection."},
                ],
                "key_takeaway_tip": "Ask your local health center or school health program about free or subsidized HPV vaccination.",
            },
        ]

        created_articles = []
        for a_data in articles_data:
            topic_obj = Topic.objects.filter(name=a_data["topic_name"]).first()
            if not topic_obj:
                continue

            article_obj, created = Article.objects.get_or_create(
                title=a_data["title"],
                defaults={
                    "topic": topic_obj,
                    "summary": a_data["summary"],
                    "content": a_data["content"],
                    "cover_image": a_data["cover_image"],
                    "content_type": a_data["content_type"],
                    "reading_time_minutes": a_data["reading_time_minutes"],
                    "sections": a_data["sections"],
                    "key_takeaway_tip": a_data["key_takeaway_tip"],
                    "author": admin_user,
                    "status": "PUBLISHED",
                }
            )
            created_articles.append(article_obj)

        # Link articles sequentially where relevant
        for i in range(len(created_articles) - 1):
            if not created_articles[i].next_article:
                created_articles[i].next_article = created_articles[i + 1]
                created_articles[i].save(update_fields=["next_article"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Successfully seeded {len(categories_data)} categories, {sum(len(c['topics']) for c in categories_data)} topics, and {len(created_articles)} published articles!"
            )
        )
