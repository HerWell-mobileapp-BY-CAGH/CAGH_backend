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


import math
from django.db import models
from rest_framework.decorators import action


def _haversine_distance(lat1, lon1, lat2, lon2):
    """Calculates geodesic distance in kilometers using the Haversine formula."""
    try:
        lat1, lon1, lat2, lon2 = map(float, [lat1, lon1, lat2, lon2])
    except (TypeError, ValueError):
        return None

    R = 6371.0  # Earth's radius in kilometers
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)


class FacilityViewSet(viewsets.ModelViewSet):
    """
    3.11 Health Facility Locator Module
    FR-027: Healthcare Facility Search & Filtering (GPS or Manual Location, Type Filter)
    FR-028: Facility Information, Contact & Navigation Directions
    """

    queryset = Facility.objects.filter(is_active=True)
    serializer_class = FacilitySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    @extend_schema(summary="Search & list nearby healthcare facilities", tags=["Common"])
    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()

        # 1. Type Filter (HOSPITAL, HEALTH_CENTER, CLINIC, PHARMACY, LABORATORY)
        facility_type = request.query_params.get('facility_type') or request.query_params.get('type')
        if facility_type:
            queryset = queryset.filter(facility_type__iexact=facility_type.strip())

        # 2. Text Search (Name, Address, City, Region, Available Services)
        search_query = request.query_params.get('q') or request.query_params.get('search')
        if search_query:
            q = search_query.strip()
            queryset = queryset.filter(
                models.Q(name__icontains=q) |
                models.Q(address__icontains=q) |
                models.Q(city__icontains=q) |
                models.Q(region__icontains=q) |
                models.Q(available_services__icontains=q)
            )

        facilities = list(queryset)

        # 3. GPS / Manual Location Distance Calculation
        user_lat = request.query_params.get('lat') or request.query_params.get('latitude')
        user_lng = request.query_params.get('lng') or request.query_params.get('longitude')
        radius_km = request.query_params.get('radius_km') or request.query_params.get('max_distance')

        if user_lat and user_lng:
            for facility in facilities:
                if facility.latitude is not None and facility.longitude is not None:
                    facility.distance_km = _haversine_distance(
                        user_lat, user_lng, facility.latitude, facility.longitude
                    )
                else:
                    facility.distance_km = None

            # Filter by radius if specified
            if radius_km:
                try:
                    max_r = float(radius_km)
                    facilities = [f for f in facilities if f.distance_km is not None and f.distance_km <= max_r]
                except ValueError:
                    pass

            # Sort by distance (closest first)
            facilities.sort(key=lambda f: f.distance_km if f.distance_km is not None else float('inf'))

        serializer = self.get_serializer(facilities, many=True)
        return Response(serializer.data)

    @extend_schema(summary="Get navigation directions & contact links for a facility", tags=["Common"])
    @action(detail=True, methods=['get'])
    def directions(self, request, pk=None):
        facility = self.get_object()
        user_lat = request.query_params.get('lat') or request.query_params.get('latitude')
        user_lng = request.query_params.get('lng') or request.query_params.get('longitude')

        distance_km = None
        if user_lat and user_lng and facility.latitude and facility.longitude:
            distance_km = _haversine_distance(user_lat, user_lng, facility.latitude, facility.longitude)

        google_maps_url = ""
        if facility.latitude and facility.longitude:
            if user_lat and user_lng:
                google_maps_url = f"https://www.google.com/maps/dir/?api=1&origin={user_lat},{user_lng}&destination={facility.latitude},{facility.longitude}"
            else:
                google_maps_url = f"https://www.google.com/maps/search/?api=1&query={facility.latitude},{facility.longitude}"

        return Response({
            "facility": {
                "id": str(facility.id),
                "name": facility.name,
                "facility_type": facility.facility_type,
                "address": facility.address,
                "phone_number": facility.phone_number,
                "operating_hours": facility.operating_hours,
                "available_services": facility.available_services,
                "latitude": float(facility.latitude) if facility.latitude else None,
                "longitude": float(facility.longitude) if facility.longitude else None,
            },
            "user_location": {
                "latitude": float(user_lat) if user_lat else None,
                "longitude": float(user_lng) if user_lng else None,
            },
            "distance_km": distance_km,
            "navigation_urls": {
                "google_maps": google_maps_url,
            },
            "call_url": f"tel:{facility.phone_number}" if facility.phone_number else None,
        })



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
