from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import Category, Topic, Article, Bookmark


class TopicInline(admin.TabularInline):
    model = Topic
    extra = 1
    fields = ('name', 'slug', 'icon', 'order')
    prepopulated_fields = {'slug': ('name',)}


class ArticleInline(admin.TabularInline):
    model = Article
    extra = 0
    fields = ('title', 'content_type', 'status', 'reading_time_minutes', 'published_at')
    readonly_fields = ('published_at',)
    show_change_link = True


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'icon', 'order', 'topics_count')
    list_editable = ('order',)
    search_fields = ('name', 'description', 'subtitle_summary')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('order', 'name')
    inlines = [TopicInline]

    def topics_count(self, obj):
        return obj.topics.count()
    topics_count.short_description = _("Topics")


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ('name', 'category', 'slug', 'order', 'articles_count')
    list_filter = ('category',)
    list_editable = ('order',)
    search_fields = ('name', 'description', 'category__name')
    prepopulated_fields = {'slug': ('name',)}
    ordering = ('category', 'order', 'name')
    inlines = [ArticleInline]

    def articles_count(self, obj):
        return obj.articles.count()
    articles_count.short_description = _("Articles")


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'topic',
        'get_category',
        'content_type',
        'status',
        'reading_time_minutes',
        'views_count',
        'author',
        'published_at',
    )
    list_filter = ('status', 'content_type', 'topic__category', 'topic', 'published_at')
    search_fields = ('title', 'summary', 'content', 'topic__name', 'topic__category__name')
    readonly_fields = ('views_count', 'created_at', 'updated_at')
    autocomplete_fields = ('next_article',)
    actions = ['mark_as_published', 'mark_as_draft', 'mark_as_review', 'mark_as_archived']

    fieldsets = (
        (_("Basic Details"), {
            "fields": ("title", "topic", "content_type", "status", "cover_image"),
        }),
        (_("Article Content"), {
            "fields": ("summary", "content", "key_takeaway_tip"),
        }),
        (_("Interactive Expandable Sections"), {
            "fields": ("sections",),
            "description": _(
                "JSON array of expandable section objects matching Figma design e.g.:<br>"
                "<code>[{\"title\": \"Section Heading\", \"detail\": \"Detailed body text...\"}]</code>"
            ),
        }),
        (_("Publishing & Navigation"), {
            "fields": ("author", "next_article", "reading_time_minutes", "published_at"),
        }),
        (_("Statistics & Timestamps"), {
            "fields": ("views_count", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )

    def get_category(self, obj):
        return obj.topic.category.name if obj.topic and obj.topic.category else "-"
    get_category.short_description = _("Category")
    get_category.admin_order_field = 'topic__category__name'

    def save_model(self, request, obj, form, change):
        if not obj.author_id:
            obj.author = request.user
        super().save_model(request, obj, form, change)

    @admin.action(description=_("Mark selected articles as PUBLISHED"))
    def mark_as_published(self, request, queryset):
        updated = queryset.update(status=Article.ArticleStatus.PUBLISHED)
        self.message_user(request, f"{updated} article(s) published successfully.")

    @admin.action(description=_("Mark selected articles as DRAFT"))
    def mark_as_draft(self, request, queryset):
        updated = queryset.update(status=Article.ArticleStatus.DRAFT)
        self.message_user(request, f"{updated} article(s) set to draft.")

    @admin.action(description=_("Mark selected articles as UNDER REVIEW"))
    def mark_as_review(self, request, queryset):
        updated = queryset.update(status=Article.ArticleStatus.REVIEW)
        self.message_user(request, f"{updated} article(s) moved to review.")

    @admin.action(description=_("Mark selected articles as ARCHIVED"))
    def mark_as_archived(self, request, queryset):
        updated = queryset.update(status=Article.ArticleStatus.ARCHIVED)
        self.message_user(request, f"{updated} article(s) archived.")


@admin.register(Bookmark)
class BookmarkAdmin(admin.ModelAdmin):
    list_display = ('user', 'article', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('user__username', 'user__email', 'article__title')
    readonly_fields = ('created_at',)
