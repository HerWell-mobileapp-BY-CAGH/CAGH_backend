from rest_framework import viewsets, permissions, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiResponse
from django.utils.translation import activate
from django.conf import settings

from .models import (
    Facility,
    AuditLog,
    Report,
    TranslationKey,
    TranslationValue,
    TranslationVersion,
)
from .serializers import (
    FacilitySerializer,
    AuditLogSerializer,
    ReportSerializer,
    LanguageSelectionSerializer,
    TranslationDictionaryResponseSerializer,
    TranslationKeyManageSerializer,
    TranslationValueManageSerializer,
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
    Returns list of supported application languages (English, Amharic).
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
    Saves language preference for current session or authenticated user.
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


class TranslationListView(APIView):
    """
    Returns published translations for a requested language with ETag and versioning support.
    """

    permission_classes = [permissions.AllowAny]

    @extend_schema(
        summary="Fetch published translations dictionary",
        description="Returns key-value translations for a requested language with version tracking and conditional caching.",
        parameters=[
            OpenApiParameter(
                name="lang",
                description="Language code ('en', 'am'). Defaults to 'en'.",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="version",
                description="Optional client-cached translation schema version. If up-to-date, returns up_to_date=True.",
                required=False,
                type=int,
            ),
            OpenApiParameter(
                name="category",
                description="Optional filter by category (e.g. 'auth', 'home').",
                required=False,
                type=str,
            ),
        ],
        responses={
            200: TranslationDictionaryResponseSerializer,
            304: OpenApiResponse(description="Translations not modified (ETag match)"),
            400: OpenApiResponse(description="Unsupported language code"),
        },
        tags=["Common"],
    )
    def get(self, request):
        lang = request.query_params.get("lang", "en").strip().lower()
        supported_codes = {item["code"] for item in SUPPORTED_LANGUAGES}

        if lang not in supported_codes:
            return Response(
                {
                    "error": f"Unsupported language '{lang}'. Supported language codes are: {', '.join(sorted(supported_codes))}."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        current_version = TranslationVersion.get_version(lang)
        etag = f'W/"{lang}-v{current_version}"'

        # Check HTTP ETag header
        if_none_match = request.headers.get("If-None-Match")
        if if_none_match and if_none_match.strip() == etag:
            response = Response(status=status.HTTP_304_NOT_MODIFIED)
            response["ETag"] = etag
            response["Cache-Control"] = "public, max-age=300"
            return response

        # Check optional client version query parameter
        client_version = request.query_params.get("version")
        if client_version is not None:
            try:
                if int(client_version) == current_version:
                    response = Response(
                        {
                            "language": lang,
                            "version": current_version,
                            "up_to_date": True,
                            "count": 0,
                            "translations": {},
                        },
                        status=status.HTTP_200_OK,
                    )
                    response["ETag"] = etag
                    response["Cache-Control"] = "public, max-age=300"
                    return response
            except (ValueError, TypeError):
                pass

        # Query published translations
        tv_qs = TranslationValue.objects.filter(
            language=lang,
            status=TranslationValue.Status.PUBLISHED,
        ).select_related("key")

        category = request.query_params.get("category")
        if category:
            tv_qs = tv_qs.filter(key__category=category)

        translations = {tv.key.key: tv.value for tv in tv_qs}

        # For English, include default_text from TranslationKey if not overridden
        if lang == "en":
            tk_qs = TranslationKey.objects.all()
            if category:
                tk_qs = tk_qs.filter(category=category)
            for tk in tk_qs:
                if tk.key not in translations:
                    translations[tk.key] = tk.default_text

        response_data = {
            "language": lang,
            "version": current_version,
            "up_to_date": False,
            "count": len(translations),
            "translations": translations,
        }

        response = Response(response_data, status=status.HTTP_200_OK)
        response["ETag"] = etag
        response["Cache-Control"] = "public, max-age=300"
        return response


class TranslationKeyViewSet(viewsets.ModelViewSet):
    queryset = TranslationKey.objects.all().prefetch_related("translations")
    serializer_class = TranslationKeyManageSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        qs = super().get_queryset()
        category = self.request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(models.Q(key__icontains=search) | models.Q(default_text__icontains=search))
        return qs

    @action(detail=False, methods=["get"], permission_classes=[permissions.IsAdminUser])
    def audit(self, request):
        """Returns translation coverage and completeness audit report across all supported languages."""
        all_keys = list(TranslationKey.objects.all())
        total_keys = len(all_keys)
        supported_codes = [l["code"] for l in SUPPORTED_LANGUAGES]

        report = {
            "total_keys": total_keys,
            "languages": {},
            "has_missing": False,
        }

        for lang in supported_codes:
            values_qs = TranslationValue.objects.filter(language=lang)
            value_map = {tv.key_id: tv for tv in values_qs}

            missing_keys = []
            unpublished_keys = []
            published_count = 0

            for tk in all_keys:
                tv = value_map.get(tk.id)
                if not tv:
                    missing_keys.append(tk.key)
                elif tv.status != TranslationValue.Status.PUBLISHED:
                    unpublished_keys.append(tk.key)
                else:
                    published_count += 1

            coverage = round((published_count / total_keys * 100), 2) if total_keys else 0.0
            version = TranslationVersion.get_version(lang)

            if missing_keys or unpublished_keys:
                report["has_missing"] = True

            report["languages"][lang] = {
                "version": version,
                "published_count": published_count,
                "missing_count": len(missing_keys),
                "unpublished_count": len(unpublished_keys),
                "coverage_pct": coverage,
                "missing_keys": missing_keys,
            }

        return Response(report, status=status.HTTP_200_OK)


class TranslationValueViewSet(viewsets.ModelViewSet):
    queryset = TranslationValue.objects.all().select_related("key")
    serializer_class = TranslationValueManageSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        qs = super().get_queryset()
        lang = self.request.query_params.get("language")
        if lang:
            qs = qs.filter(language=lang.strip().lower())
        status_filter = self.request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter.upper())
        search = self.request.query_params.get("search")
        if search:
            qs = qs.filter(models.Q(key__key__icontains=search) | models.Q(value__icontains=search))
        return qs

    @action(detail=False, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def publish(self, request):
        """Bulk publish translations by ID and bump version for affected languages."""
        ids = request.data.get("ids", [])
        if not ids or not isinstance(ids, list):
            return Response({"error": "List of 'ids' required."}, status=status.HTTP_400_BAD_REQUEST)

        translations = TranslationValue.objects.filter(id__in=ids)
        updated = translations.update(status=TranslationValue.Status.PUBLISHED)
        languages = set(translations.values_list("language", flat=True))
        for lang in languages:
            TranslationVersion.bump(lang)

        return Response(
            {"message": f"{updated} translation(s) published.", "affected_languages": list(languages)},
            status=status.HTTP_200_OK,
        )


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


def _fetch_google_places(user_lat, user_lng, radius_km=10, facility_type=None, search_query=None):
    """Fetches real-world nearby healthcare facilities dynamically from Google Places API."""
    try:
        import requests
    except ImportError:
        return []

    api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')
    if not api_key:
        return []

    try:
        radius_meters = int(float(radius_km) * 1000)
    except (TypeError, ValueError):
        radius_meters = 10000

    type_mapping = {
        'HOSPITAL': 'hospital',
        'HEALTH_CENTER': 'hospital',
        'CLINIC': 'doctor',
        'PHARMACY': 'pharmacy',
        'LABORATORY': 'doctor',
    }
    g_type = type_mapping.get((facility_type or '').upper(), 'hospital')

    params = {
        'location': f"{user_lat},{user_lng}",
        'radius': radius_meters,
        'type': g_type,
        'key': api_key,
    }
    if search_query:
        params['keyword'] = search_query

    try:
        res = requests.get('https://maps.googleapis.com/maps/api/place/nearbysearch/json', params=params, timeout=5)
        if res.status_code != 200:
            return []

        data = res.json()
        results = data.get('results', [])
        places = []
        for p in results:
            p_lat = p.get('geometry', {}).get('location', {}).get('lat')
            p_lng = p.get('geometry', {}).get('location', {}).get('lng')
            dist = _haversine_distance(user_lat, user_lng, p_lat, p_lng)

            places.append({
                'id': p.get('place_id'),
                'name': p.get('name'),
                'facility_type': (facility_type or 'HOSPITAL').upper(),
                'address': p.get('vicinity', ''),
                'city': '',
                'region': '',
                'phone_number': '',
                'operating_hours': 'Open Now' if p.get('opening_hours', {}).get('open_now') else 'Closed/Unknown',
                'available_services': [g_type.title()],
                'latitude': p_lat,
                'longitude': p_lng,
                'distance_km': dist,
                'rating_average': float(p.get('rating', 0.0)),
                'rating_count': int(p.get('user_ratings_total', 0)),
                'is_active': True,
                'source': 'GOOGLE_PLACES',
            })
        return places
    except Exception:
        return []


def _fetch_google_place_details(place_id):
    """Fetches details (phone number, coordinates, navigation URL) for a Google Place ID."""
    try:
        import requests
    except ImportError:
        return None

    api_key = getattr(settings, 'GOOGLE_MAPS_API_KEY', '')
    if not api_key or not place_id:
        return None

    try:
        url = "https://maps.googleapis.com/maps/api/place/details/json"
        params = {
            "place_id": place_id,
            "fields": "name,vicinity,formatted_phone_number,geometry,rating,user_ratings_total,opening_hours,url",
            "key": api_key,
        }
        res = requests.get(url, params=params, timeout=5)
        if res.status_code == 200:
            data = res.json().get("result", {})
            p_lat = data.get("geometry", {}).get("location", {}).get("lat")
            p_lng = data.get("geometry", {}).get("location", {}).get("lng")
            return {
                "id": place_id,
                "name": data.get("name", ""),
                "address": data.get("vicinity", ""),
                "phone_number": data.get("formatted_phone_number", ""),
                "latitude": p_lat,
                "longitude": p_lng,
                "google_url": data.get("url", ""),
            }
    except Exception:
        pass
    return None


class FacilityViewSet(viewsets.ModelViewSet):
    """
    Health Facility Locator Module.
    Handles healthcare facility search, geolocation filtering, and navigation details.
    """

    queryset = Facility.objects.filter(is_active=True)
    serializer_class = FacilitySerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    @extend_schema(summary="Search & list nearby healthcare facilities", tags=["Common"])
    def list(self, request, *args, **kwargs):
        user_lat = request.query_params.get('lat') or request.query_params.get('latitude')
        user_lng = request.query_params.get('lng') or request.query_params.get('longitude')
        radius_km = request.query_params.get('radius_km') or request.query_params.get('max_distance') or 10
        facility_type = request.query_params.get('facility_type') or request.query_params.get('type')
        search_query = request.query_params.get('q') or request.query_params.get('search')

        # 1. Dynamically fetch real-world facilities via Google Places API if user GPS is available & API key configured
        google_places = []
        if user_lat and user_lng:
            google_places = _fetch_google_places(
                user_lat, user_lng, radius_km=radius_km, facility_type=facility_type, search_query=search_query
            )

        # 2. Query local database facilities as fallback or complementary results
        queryset = self.get_queryset()
        if facility_type:
            queryset = queryset.filter(facility_type__iexact=facility_type.strip())

        if search_query:
            q = search_query.strip()
            queryset = queryset.filter(
                models.Q(name__icontains=q) |
                models.Q(address__icontains=q) |
                models.Q(city__icontains=q) |
                models.Q(region__icontains=q) |
                models.Q(available_services__icontains=q)
            )

        if user_lat and user_lng and radius_km:
            try:
                u_lat = float(user_lat)
                u_lng = float(user_lng)
                r_km = float(radius_km)
                d_lat = r_km / 111.0
                d_lng = r_km / (111.0 * max(math.cos(math.radians(u_lat)), 0.01))

                queryset = queryset.filter(
                    latitude__gte=u_lat - d_lat,
                    latitude__lte=u_lat + d_lat,
                    longitude__gte=u_lng - d_lng,
                    longitude__lte=u_lng + d_lng,
                )
            except (ValueError, TypeError):
                pass

        db_facilities = list(queryset)

        if user_lat and user_lng:
            for facility in db_facilities:
                if facility.latitude is not None and facility.longitude is not None:
                    facility.distance_km = _haversine_distance(
                        user_lat, user_lng, facility.latitude, facility.longitude
                    )
                else:
                    facility.distance_km = None

            if radius_km:
                try:
                    max_r = float(radius_km)
                    db_facilities = [f for f in db_facilities if f.distance_km is not None and f.distance_km <= max_r]
                except ValueError:
                    pass

        serialized_db = self.get_serializer(db_facilities, many=True).data

        # 3. Merge Google Places results with DB results (Google Places results take priority if available)
        combined_results = google_places + serialized_db
        combined_results.sort(key=lambda f: f.get('distance_km') if f.get('distance_km') is not None else float('inf'))

        return Response(combined_results)

    @extend_schema(summary="Get navigation directions & contact links for a facility", tags=["Common"])
    @action(detail=True, methods=['get'])
    def directions(self, request, pk=None):
        user_lat = request.query_params.get('lat') or request.query_params.get('latitude')
        user_lng = request.query_params.get('lng') or request.query_params.get('longitude')

        facility_data = None
        place_details = _fetch_google_place_details(pk)

        if place_details:
            facility_data = place_details
        else:
            try:
                fac = self.get_object()
                facility_data = {
                    "id": str(fac.id),
                    "name": fac.name,
                    "facility_type": fac.facility_type,
                    "address": fac.address,
                    "phone_number": fac.phone_number,
                    "operating_hours": fac.operating_hours,
                    "available_services": fac.available_services,
                    "latitude": float(fac.latitude) if fac.latitude else None,
                    "longitude": float(fac.longitude) if fac.longitude else None,
                }
            except Exception:
                return Response({"error": "Facility not found."}, status=status.HTTP_404_NOT_FOUND)

        dest_lat = facility_data.get("latitude")
        dest_lng = facility_data.get("longitude")
        phone = facility_data.get("phone_number", "")

        distance_km = None
        if user_lat and user_lng and dest_lat and dest_lng:
            distance_km = _haversine_distance(user_lat, user_lng, dest_lat, dest_lng)

        google_maps_url = facility_data.get("google_url", "")
        if not google_maps_url and dest_lat and dest_lng:
            if user_lat and user_lng:
                google_maps_url = f"https://www.google.com/maps/dir/?api=1&origin={user_lat},{user_lng}&destination={dest_lat},{dest_lng}"
                if place_details:
                    google_maps_url += f"&destination_place_id={pk}"
            else:
                google_maps_url = f"https://www.google.com/maps/search/?api=1&query={dest_lat},{dest_lng}"

        return Response({
            "facility": facility_data,
            "user_location": {
                "latitude": float(user_lat) if user_lat else None,
                "longitude": float(user_lng) if user_lng else None,
            },
            "distance_km": distance_km,
            "navigation_urls": {
                "google_maps": google_maps_url,
            },
            "call_url": f"tel:{phone}" if phone else None,
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
