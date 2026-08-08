from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from apps.learning.models import Category, Topic, Article, Bookmark

User = get_user_model()


class LearningCenterTestCase(APITestCase):

    def setUp(self):
        # Create Patient User
        self.patient = User.objects.create_user(
            username="patient_learning",
            email="patient_learn@example.com",
            password="PatientPassword123!",
            role="PATIENT",
        )

        # Create Midwife User
        self.midwife = User.objects.create_user(
            username="midwife_learning",
            email="midwife_learn@example.com",
            password="MidwifePassword123!",
            role="MIDWIFE",
        )

        # Create Category & Topics
        self.category = Category.objects.create(
            name="Adolescent Girls Health & Nutrition",
            slug="adolescent-girls-health-nutrition",
            subtitle_summary="Puberty, menstrual health, nutrition & healthy lifestyle",
            icon="sparkles",
            order=1,
        )

        self.puberty_topic = Topic.objects.create(
            category=self.category,
            name="Puberty",
            slug="puberty",
            order=1,
        )

        self.menstruation_topic = Topic.objects.create(
            category=self.category,
            name="Menstruation",
            slug="menstruation",
            order=2,
        )

        # Create Articles
        self.menstruation_article = Article.objects.create(
            topic=self.menstruation_topic,
            title="Menstruation Guide",
            content="Understanding your menstrual cycle...",
            author=self.midwife,
            status="PUBLISHED",
        )

        self.puberty_article = Article.objects.create(
            topic=self.puberty_topic,
            title="What is Puberty?",
            summary="Puberty is a natural part of growing up.",
            content="Puberty is a natural part of growing up...",
            sections=[
                {"title": "Breast development", "detail": "Small swellings form."},
                {"title": "Growing taller", "detail": "Growth spurt in height."},
            ],
            key_takeaway_tip="Every girl grows differently.",
            next_article=self.menstruation_article,
            author=self.midwife,
            status="PUBLISHED",
        )

    def test_list_categories_matching_figma_screen1(self):
        url = reverse("category-list")
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Adolescent Girls Health & Nutrition")
        self.assertEqual(results[0]["topics_count"], 2)

    def test_list_topics_filtered_by_category_slug(self):
        url = reverse("topic-list")
        res = self.client.get(url, {"category_slug": "adolescent-girls-health-nutrition"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(results), 2)

    def test_article_detail_view_matching_figma_screen6(self):
        url = reverse("article-detail", kwargs={"pk": self.puberty_article.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["title"], "What is Puberty?")
        self.assertEqual(len(res.data["sections"]), 2)
        self.assertEqual(res.data["key_takeaway_tip"], "Every girl grows differently.")
        self.assertIsNotNone(res.data["next_article_detail"])
        self.assertEqual(res.data["next_article_detail"]["title"], "Menstruation Guide")

    def test_bookmark_toggle_for_patient_and_midwife(self):
        url = reverse("article-bookmark", kwargs={"pk": self.puberty_article.id})

        # Test Patient Bookmark
        self.client.force_authenticate(user=self.patient)
        res_bookmark = self.client.post(url)
        self.assertEqual(res_bookmark.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res_bookmark.data["is_bookmarked"])

        # Test Midwife Bookmark
        self.client.force_authenticate(user=self.midwife)
        res_mw_bookmark = self.client.post(url)
        self.assertEqual(res_mw_bookmark.status_code, status.HTTP_201_CREATED)
        self.assertTrue(res_mw_bookmark.data["is_bookmarked"])

    def test_search_articles(self):
        url = reverse("article-list")
        res = self.client.get(url, {"q": "Puberty"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "What is Puberty?")
