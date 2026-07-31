from django.contrib import admin
from .models import Category, Topic, Article, Bookmark

admin.site.register(Category)
admin.site.register(Topic)
admin.site.register(Article)
admin.site.register(Bookmark)
