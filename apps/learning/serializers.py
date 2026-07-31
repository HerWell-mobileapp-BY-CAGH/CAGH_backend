from rest_framework import serializers
from .models import Category, Topic, Article, Bookmark
from apps.users.user_serializers import UserSerializer


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'


class TopicSerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source='category.name')

    class Meta:
        model = Topic
        fields = '__all__'


class ArticleSerializer(serializers.ModelSerializer):
    author_detail = UserSerializer(source='author', read_only=True)
    topic_detail = TopicSerializer(source='topic', read_only=True)

    class Meta:
        model = Article
        fields = '__all__'
        read_only_fields = ('id', 'author', 'created_at', 'updated_at')


class BookmarkSerializer(serializers.ModelSerializer):
    article_detail = ArticleSerializer(source='article', read_only=True)

    class Meta:
        model = Bookmark
        fields = '__all__'
        read_only_fields = ('id', 'user', 'created_at')
