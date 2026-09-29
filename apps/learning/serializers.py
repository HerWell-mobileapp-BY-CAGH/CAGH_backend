from rest_framework import serializers
from .models import Category, Topic, Article, Bookmark
from apps.users.user_serializers import UserSerializer


class TopicSerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source='category.name')
    articles_count = serializers.SerializerMethodField()

    class Meta:
        model = Topic
        fields = '__all__'
        # These are calculated response fields, never client supplied values.
        read_only_fields = ('id', 'category_name', 'articles_count')

    def get_articles_count(self, obj):
        return obj.articles.filter(status=Article.ArticleStatus.PUBLISHED).count()


class CategorySerializer(serializers.ModelSerializer):
    topics = TopicSerializer(many=True, read_only=True)
    topics_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = '__all__'
        # Nested topics and the count are response-only representations.
        read_only_fields = ('id', 'topics', 'topics_count')

    def get_topics_count(self, obj):
        return obj.topics.count()


class ArticleSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    topic_name = serializers.ReadOnlyField(source='topic.name')
    category_name = serializers.ReadOnlyField(source='topic.category.name')
    is_bookmarked = serializers.SerializerMethodField()
    next_article_detail = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = '__all__'
        # The server owns attribution and analytics.  In particular, clients
        # must not be able to create an article in another user's name.
        read_only_fields = (
            'id', 'author', 'author_name', 'topic_name', 'category_name',
            'is_bookmarked', 'next_article_detail', 'views_count',
            'created_at', 'updated_at',
        )

    def get_author_name(self, obj):
        if obj.author:
            first = getattr(obj.author, 'first_name', '')
            last = getattr(obj.author, 'last_name', '')
            name = f"{first} {last}".strip()
            return name if name else obj.author.username
        return "HerWell Health Editorial Team"

    def get_is_bookmarked(self, obj):
        request = self.context.get('request')
        if request and request.user and request.user.is_authenticated:
            return Bookmark.objects.filter(user=request.user, article=obj).exists()
        return False

    def get_next_article_detail(self, obj):
        if obj.next_article:
            return {
                "id": str(obj.next_article.id),
                "title": obj.next_article.title,
                "topic_name": obj.next_article.topic.name if obj.next_article.topic else "",
            }
        return None


class BookmarkSerializer(serializers.ModelSerializer):
    article_detail = ArticleSerializer(source='article', read_only=True)

    class Meta:
        model = Bookmark
        fields = '__all__'
        read_only_fields = ('id', 'user', 'created_at')

