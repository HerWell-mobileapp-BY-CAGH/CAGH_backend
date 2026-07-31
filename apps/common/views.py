from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiResponse
from django.utils.translation import activate
from django.conf import settings

from .models import Facility, AuditLog, Report
from .serializers import (
    FacilitySerializer,
    AuditLogSerializer,
    ReportSerializer,
    LanguageSelectionSerializer,
)

SUPPORTED_LANGUAGES = [
    {
        "code": "en",
        "name": "English",
        "native_name": "English",
        "is_default": True,
    },
    {
        "code": "am",
        "name": "Amharic",
        "native_name": "አማርኛ",
        "is_default": False,
    },
]


class LanguageListView(APIView):
    """
    FR-000 Initial Language Selection: Display supported languages (English, Amharic).
    """

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="List supported languages",
        description="Returns list of supported application languages (English, Amharic).",
        responses={200: OpenApiResponse(description="List of supported languages")},
        tags=["Common"],
    )
    def get(self, request):
        return Response(
            {
                "default_language": "en",
                "supported_languages": SUPPORTED_LANGUAGES,
            },
            status=status.HTTP_200_OK,
        )


class LanguageSelectView(APIView):
    """
    FR-000 Initial Language Selection: Save language preference.
    """

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Select/save language preference",
        request=LanguageSelectionSerializer,
        responses={
            200: OpenApiResponse(description="Language saved successfully"),
            400: OpenApiResponse(description="Invalid language selection"),
        },
        tags=["Common"],
    )
    def post(self, request):
        serializer = LanguageSelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        input_lang = serializer.validated_data["language"].strip().lower()

        lang_map = {
            "en": ("en", "English", "English"),
            "english": ("en", "English", "English"),
            "am": ("am", "Amharic", "አማርኛ"),
            "amharic": ("am", "Amharic", "አማርኛ"),
        }

        if input_lang not in lang_map:
            return Response(
                {"error": "Unsupported language. Supported languages are 'en' (English) and 'am' (Amharic)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        code, name, native_name = lang_map[input_lang]

        activate(code)
        if hasattr(request, "session"):
            request.session["django_language"] = code

        if request.user and request.user.is_authenticated and hasattr(request.user, "profile"):
            profile = request.user.profile
            profile.preferred_language = code
            profile.save()

        response = Response(
            {
                "message": "Language preference saved successfully.",
                "language": code,
                "name": name,
                "native_name": native_name,
            },
            status=status.HTTP_200_OK,
        )

        response.set_cookie(getattr(settings, "LANGUAGE_COOKIE_NAME", "django_language"), code)
        return response


class FacilityViewSet(viewsets.ModelViewSet):
    queryset = Facility.objects.all()
    serializer_class = FacilitySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditLog.objects.all()
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAdminUser]


class ReportViewSet(viewsets.ModelViewSet):
    queryset = Report.objects.all()
    serializer_class = ReportSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if self.request.user.is_staff:
            return Report.objects.all()
        return Report.objects.filter(reporter=self.request.user)

    def perform_create(self, serializer):
        serializer.save(reporter=self.request.user)
