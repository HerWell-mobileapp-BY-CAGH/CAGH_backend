from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.test import override_settings
from django.contrib.auth import get_user_model
from apps.learning.models import Category, Topic, Article, Bookmark

User = get_user_model()


@override_settings(SECURE_SSL_REDIRECT=False)
class LearningCenterTestCase(APITestCase):

    @staticmethod
    def learning_url(name, **kwargs):
        """Return a canonical trailing-slash DRF URL for test requests.

        This project redirects slashless paths through Django's CommonMiddleware.
        API tests intentionally use the final route so mutation requests are not
        converted into redirects before the view permission code runs.
        """
        url = reverse(name, kwargs=kwargs)
        return url if url.endswith("/") else f"{url}/"

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

        # Editorial write tests use an application ADMIN, not merely a Django
        # staff account, to prove the role-based production authorization path.
        self.admin = User.objects.create_user(
            username="learning_admin",
            email="learning_admin@example.com",
            password="AdminPassword123!",
            role="ADMIN",
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
        url = self.learning_url("category-list")
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["name"], "Adolescent Girls Health & Nutrition")
        self.assertEqual(results[0]["topics_count"], 2)

    def test_list_topics_filtered_by_category_slug(self):
        url = self.learning_url("topic-list")
        res = self.client.get(url, {"category_slug": "adolescent-girls-health-nutrition"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(results), 2)

    def test_article_detail_view_matching_figma_screen6(self):
        url = self.learning_url("article-detail", pk=self.puberty_article.id)
        res = self.client.get(url)
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data["title"], "What is Puberty?")
        self.assertEqual(len(res.data["sections"]), 2)
        self.assertEqual(res.data["key_takeaway_tip"], "Every girl grows differently.")
        self.assertIsNotNone(res.data["next_article_detail"])
        self.assertEqual(res.data["next_article_detail"]["title"], "Menstruation Guide")

    def test_bookmark_toggle_for_patient_and_midwife(self):
        url = self.learning_url("article-bookmark", pk=self.puberty_article.id)

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
        url = self.learning_url("article-list")
        res = self.client.get(url, {"q": "Puberty"})
        self.assertEqual(res.status_code, status.HTTP_200_OK)
        results = res.data["results"] if isinstance(res.data, dict) else res.data
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "What is Puberty?")

    def test_only_admin_can_create_update_and_delete_learning_content(self):
        """Patients and midwives can read, but cannot change editorial data."""
        category_url = self.learning_url("category-list")
        topic_url = self.learning_url("topic-list")
        article_url = self.learning_url("article-list")

        self.client.force_authenticate(user=self.patient)
        self.assertEqual(
            self.client.post(category_url, {"name": "Blocked", "slug": "blocked"}).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.patch(
                self.learning_url("topic-detail", pk=self.puberty_topic.id),
                {"name": "Blocked edit"},
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        self.assertEqual(
            self.client.delete(
                self.learning_url("article-detail", pk=self.puberty_article.id)
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.client.force_authenticate(user=self.admin)
        category_response = self.client.post(
            category_url, {"name": "New category", "slug": "new-category"}, format="json"
        )
        self.assertEqual(category_response.status_code, status.HTTP_201_CREATED)
        topic_response = self.client.post(
            topic_url,
            {"name": "New topic", "slug": "new-topic", "category": str(self.category.id)},
            format="json",
        )
        self.assertEqual(topic_response.status_code, status.HTTP_201_CREATED)
        article_response = self.client.post(
            article_url,
            {
                "title": "Admin article", "content": "Editorial body.",
                "topic": str(self.puberty_topic.id), "status": "DRAFT",
            },
            format="json",
        )
        self.assertEqual(article_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(str(article_response.data["author"]), str(self.admin.id))

        self.assertEqual(
            self.client.patch(
                self.learning_url("category-detail", id=category_response.data["id"]),
                {"description": "Updated by an administrator"},
                format="json",
            ).status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.delete(
                self.learning_url("topic-detail", pk=topic_response.data["id"])
            ).status_code,
            status.HTTP_204_NO_CONTENT,
        )

    def test_only_admin_can_fetch_non_published_learning_materials(self):
        """Status filters expose the editorial queues without leaking drafts."""
        Article.objects.create(
            topic=self.puberty_topic,
            title="Draft article",
            content="Not public yet.",
            author=self.admin,
            status=Article.ArticleStatus.DRAFT,
        )
        Article.objects.create(
            topic=self.puberty_topic,
            title="Review article",
            content="Awaiting review.",
            author=self.admin,
            status=Article.ArticleStatus.REVIEW,
        )
        Article.objects.create(
            topic=self.puberty_topic,
            title="Archived article",
            content="Kept for record only.",
            author=self.admin,
            status=Article.ArticleStatus.ARCHIVED,
        )
        article_url = self.learning_url("article-list")

        # A patient asking for DRAFT still gets an empty public result.
        self.client.force_authenticate(user=self.patient)
        patient_response = self.client.get(article_url, {"status": "DRAFT"})
        patient_results = patient_response.data["results"] if isinstance(patient_response.data, dict) else patient_response.data
        self.assertEqual(patient_response.status_code, status.HTTP_200_OK)
        self.assertEqual(patient_results, [])

        self.client.force_authenticate(user=self.admin)
        for material_status, expected_title in (
            ("PUBLISHED", "What is Puberty?"),
            ("DRAFT", "Draft article"),
            ("REVIEW", "Review article"),
            ("ARCHIVED", "Archived article"),
        ):
            response = self.client.get(article_url, {"status": material_status})
            results = response.data["results"] if isinstance(response.data, dict) else response.data
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            # The published fixture contains two public articles; each queue
            # must still contain the known material for its requested status.
            self.assertIn(expected_title, [article["title"] for article in results])
            self.assertTrue(all(article["status"] == material_status for article in results))
