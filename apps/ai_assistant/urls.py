from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AIQuestionViewSet, AIChatView, AIConversationViewSet

router = DefaultRouter()
router.register(r'conversations', AIConversationViewSet, basename='ai-conversation')
router.register(r'questions', AIQuestionViewSet, basename='ai-question')
router.register(r'', AIQuestionViewSet, basename='ai-root')


urlpatterns = [
    path('chat/', AIChatView.as_view(), name='ai-chat'),
    path('', include(router.urls)),
]
