from django.db import models
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiResponse

from .models import Category, Topic, Article, Bookmark
from .serializers import (
    CategorySerializer,
    TopicSerializer,
    ArticleSerializer,
    BookmarkSerializer
)


class CategoryViewSet(viewsets.ModelViewSet):
    """
    Screen 1 in Figma: List all Learning Center categories.
    Categories include:
    1. Adolescent Girls Health & Nutrition
    2. Prevention and Awareness
    3. Psychosocial Support & Protection
    4. Reproductive Health & Care
    """

    queryset = Category.objects.all().prefetch_related('topics')
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'id'


class TopicViewSet(viewsets.ModelViewSet):
    """
    Screens 2, 3, 4, 5 in Figma: List topics within a category.
    """

    queryset = Topic.objects.all().select_related('category')
    serializer_class = TopicSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = super().get_queryset()
        category_id = self.request.query_params.get('category')
        category_slug = self.request.query_params.get('category_slug')

        if category_id:
            queryset = queryset.filter(category_id=category_id)
        elif category_slug:
            queryset = queryset.filter(category__slug=category_slug)

        return queryset


class ArticleViewSet(viewsets.ModelViewSet):
    """
    Screen 6 in Figma: Article detail, reading content, key takeaway tips, expandable sections, next article link.
    Accessible to both Patients and Midwives.
    """

    queryset = Article.objects.all().select_related('topic', 'topic__category', 'author', 'next_article')
    serializer_class = ArticleSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        queryset = self.queryset

        # Non-staff users only see PUBLISHED articles
        if not (self.request.user and (self.request.user.is_staff or getattr(self.request.user, 'role', '') == 'ADMIN')):
            queryset = queryset.filter(status=Article.ArticleStatus.PUBLISHED)

        # Filters
        topic_id = self.request.query_params.get('topic')
        category_id = self.request.query_params.get('category')
        category_slug = self.request.query_params.get('category_slug')
        content_type = self.request.query_params.get('content_type')
        search_query = self.request.query_params.get('q') or self.request.query_params.get('search')

        if topic_id:
            queryset = queryset.filter(topic_id=topic_id)
        if category_id:
            queryset = queryset.filter(topic__category_id=category_id)
        if category_slug:
            queryset = queryset.filter(topic__category__slug=category_slug)
        if content_type:
            queryset = queryset.filter(content_type=content_type)
        if search_query:
            q = search_query.strip()
            queryset = queryset.filter(
                models.Q(title__icontains=q) |
                models.Q(content__icontains=q) |
                models.Q(summary__icontains=q)
            )

        return queryset

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        # Increment views count on read
        instance.views_count += 1
        instance.save(update_fields=['views_count'])

        serializer = self.get_serializer(instance, context={'request': request})
        return Response(serializer.data)

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

    @extend_schema(summary="Toggle bookmark status for an article", tags=["Learning"])
    @action(detail=True, methods=['post'], permission_classes=[permissions.IsAuthenticated])
    def bookmark(self, request, pk=None):
        article = self.get_object()
        bookmark, created = Bookmark.objects.get_or_create(user=request.user, article=article)

        if not created:
            bookmark.delete()
            return Response(
                {"message": "Article removed from bookmarks.", "is_bookmarked": False},
                status=status.HTTP_200_OK,
            )

        return Response(
            {"message": "Article saved to bookmarks.", "is_bookmarked": True},
            status=status.HTTP_201_CREATED,
        )


class BookmarkViewSet(viewsets.ModelViewSet):
    """
    List, create, or delete saved/bookmarked articles for the logged-in user or midwife.
    """

    serializer_class = BookmarkSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Bookmark.objects.filter(user=self.request.user).select_related('article', 'article__topic')

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

