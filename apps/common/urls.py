from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    FacilityViewSet,
    AuditLogViewSet,
    ReportViewSet,
    LanguageListView,
    LanguageSelectView,
    TranslationListView,
    TranslationKeyViewSet,
    TranslationValueViewSet,
)

router = DefaultRouter()
router.register(r'facilities', FacilityViewSet, basename='facility')
router.register(r'audit-logs', AuditLogViewSet, basename='audit-log')
router.register(r'reports', ReportViewSet, basename='report')
router.register(r'translations/keys', TranslationKeyViewSet, basename='translation-key')
router.register(r'translations/values', TranslationValueViewSet, basename='translation-value')

urlpatterns = [
    path('languages/', LanguageListView.as_view(), name='language-list'),
    path('languages/select/', LanguageSelectView.as_view(), name='language-select'),
    path('translations/', TranslationListView.as_view(), name='translation-list'),
    path('', include(router.urls)),
]

