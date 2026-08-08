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

        # Create sample article matching Figma Screen 6: "What is Puberty?"
        puberty_topic = Topic.objects.filter(name="Puberty").first()
        menstruation_topic = Topic.objects.filter(name="Menstruation").first()

        if puberty_topic and menstruation_topic:
            menstruation_article, _ = Article.objects.get_or_create(
                title="Menstruation & Menstrual Hygiene Guide",
                defaults={
                    "topic": menstruation_topic,
                    "summary": "Understanding your menstrual cycle, hygiene practices, and tracking your period.",
                    "content": "Menstruation is a normal biological process where the body sheds the lining of the uterus every month...",
                    "author": admin_user,
                    "status": "PUBLISHED",
                    "reading_time_minutes": 4,
                }
            )

            puberty_article, created = Article.objects.get_or_create(
                title="What is Puberty?",
                defaults={
                    "topic": puberty_topic,
                    "summary": "Puberty is a natural part of growing up. Learn about the physical and emotional changes to expect.",
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
                    "sections": [
                        {"title": "Breast development", "detail": "Small swellings (breast buds) form under the nipples."},
                        {"title": "Growing taller", "detail": "A noticeable growth spurt in height and body shape changes."},
                        {"title": "First menstrual period", "detail": "The start of regular or irregular monthly bleeding (menarche)."},
                        {"title": "Body hair growth", "detail": "Soft hair starts growing under arms and in the pubic area."},
                        {"title": "Emotional and mood changes", "detail": "Fluctuations in feelings caused by developing hormones."},
                    ],
                    "key_takeaway_tip": "Remember: Every girl grows differently. Your body develops at its own pace, and that's completely normal.",
                    "next_article": menstruation_article,
                    "author": admin_user,
                    "status": "PUBLISHED",
                    "reading_time_minutes": 3,
                }
            )

        self.stdout.write(self.style.SUCCESS("Successfully seeded Learning Center categories, topics, and sample articles!"))
