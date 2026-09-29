from django.db import models
from rest_framework import viewsets, permissions, status
from rest_framework.exceptions import ValidationError
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
from .permissions import IsAdminOrReadOnly
from apps.users.models import User


def is_learning_admin(user):
    """Return whether ``user`` may see editorial-only Learning Center data."""
    if not (user and user.is_authenticated):
        return False

    # ``role`` is the source of truth for API-created admins; ``is_staff``
    # preserves normal Django-superuser access.
    return user.is_staff or (
        User.Role.normalize(getattr(user, 'role', None)) == User.Role.ADMIN
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
    # GET is public, while POST/PATCH/PUT/DELETE require an administrator.
    permission_classes = [IsAdminOrReadOnly]
    lookup_field = 'id'


class TopicViewSet(viewsets.ModelViewSet):
    """
    Screens 2, 3, 4, 5 in Figma: List topics within a category.
    """

    queryset = Topic.objects.all().select_related('category')
    serializer_class = TopicSerializer
    # Topics are public to read, but their editorial lifecycle is admin-only.
    permission_classes = [IsAdminOrReadOnly]

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
    # Creating, editing, archiving, or deleting articles is admin-only.
    permission_classes = [IsAdminOrReadOnly]

    def get_queryset(self):
        queryset = self.queryset

        # Patients, midwives, and anonymous users must never receive drafts,
        # under-review material, or archived material from list *or* detail.
        if not is_learning_admin(self.request.user):
            queryset = queryset.filter(status=Article.ArticleStatus.PUBLISHED)

        # Filters
        topic_id = self.request.query_params.get('topic')
        category_id = self.request.query_params.get('category')
        category_slug = self.request.query_params.get('category_slug')
        content_type = self.request.query_params.get('content_type')
        material_status = self.request.query_params.get('status')
        search_query = self.request.query_params.get('q') or self.request.query_params.get('search')

        if topic_id:
            queryset = queryset.filter(topic_id=topic_id)
        if category_id:
            queryset = queryset.filter(topic__category_id=category_id)
        if category_slug:
            queryset = queryset.filter(topic__category__slug=category_slug)
        if content_type:
            queryset = queryset.filter(content_type=content_type)
        if material_status:
            normalized_status = material_status.upper()
            valid_statuses = set(Article.ArticleStatus.values)
            if normalized_status not in valid_statuses:
                raise ValidationError({
                    'status': 'Use one of: DRAFT, REVIEW, PUBLISHED, ARCHIVED.'
                })
            # Non-admin requests have already been restricted to PUBLISHED;
            # retaining that restriction prevents status-query data leaks.
            queryset = queryset.filter(status=normalized_status)
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
        # IsAdminOrReadOnly protects this path; attribution remains server-set.
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

