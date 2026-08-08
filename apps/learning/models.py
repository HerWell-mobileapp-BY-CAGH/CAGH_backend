import uuid
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Category(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150, unique=True)
    slug = models.SlugField(max_length=150, unique=True)
    icon = models.CharField(max_length=100, blank=True, default="book-open")
    subtitle_summary = models.TextField(blank=True)
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = 'Categories'
        ordering = ['order', 'name']

    def __str__(self):
        return self.name


class Topic(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='topics')
    name = models.CharField(max_length=150)
    slug = models.SlugField(max_length=150)
    icon = models.CharField(max_length=100, blank=True, default="circle-dot")
    description = models.TextField(blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'name']
        unique_together = ('category', 'slug')

    def __str__(self):
        return f"{self.name} ({self.category.name})"


class Article(models.Model):
    class ArticleStatus(models.TextChoices):
        DRAFT = 'DRAFT', _('Draft')
        REVIEW = 'REVIEW', _('Under Review')
        PUBLISHED = 'PUBLISHED', _('Published')
        ARCHIVED = 'ARCHIVED', _('Archived')

    class ContentType(models.TextChoices):
        TEXT = 'TEXT', _('Text Article')
        INFOGRAPHIC = 'INFOGRAPHIC', _('Infographic')
        VIDEO = 'VIDEO', _('Video')
        INTERACTIVE = 'INTERACTIVE', _('Interactive Guide')

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    topic = models.ForeignKey(Topic, on_delete=models.CASCADE, related_name='articles')
    title = models.CharField(max_length=255)
    summary = models.TextField(blank=True)
    content = models.TextField()
    cover_image = models.URLField(max_length=500, blank=True)
    content_type = models.CharField(
        max_length=20,
        choices=ContentType.choices,
        default=ContentType.TEXT
    )
    sections = models.JSONField(default=list, blank=True, help_text="Expandable sections matching Figma e.g. Breast development, Growing taller")
    key_takeaway_tip = models.TextField(blank=True, help_text="Highlight tip box at bottom of article")
    next_article = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='previous_articles')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='authored_articles')
    status = models.CharField(max_length=20, choices=ArticleStatus.choices, default=ArticleStatus.PUBLISHED)
    reading_time_minutes = models.PositiveIntegerField(default=3)
    views_count = models.PositiveIntegerField(default=0)
    published_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at', '-created_at']

    def __str__(self):
        return f"{self.title} ({self.status})"


class Bookmark(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookmarks')
    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='bookmarked_by')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('user', 'article')
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} bookmarked {self.article.title}"

