from django.contrib import admin
from .models import (
    Facility,
    AuditLog,
    Report,
    TranslationKey,
    TranslationValue,
    TranslationVersion,
)

admin.site.register(Facility)
admin.site.register(AuditLog)
admin.site.register(Report)


class TranslationValueInline(admin.TabularInline):
    model = TranslationValue
    extra = 1
    fields = ('language', 'value', 'status', 'reviewed_by')


@admin.register(TranslationKey)
class TranslationKeyAdmin(admin.ModelAdmin):
    list_display = ('key', 'category', 'default_text_preview', 'status_summary', 'updated_at')
    search_fields = ('key', 'default_text', 'category', 'description')
    list_filter = ('category',)
    inlines = [TranslationValueInline]

    def default_text_preview(self, obj):
        return (obj.default_text[:60] + '...') if len(obj.default_text) > 60 else obj.default_text
    default_text_preview.short_description = 'Default English Text'

    def status_summary(self, obj):
        counts = [f"{t.language.upper()}:{t.status}" for t in obj.translations.all()]
        return ", ".join(counts) if counts else "No translations"
    status_summary.short_description = 'Translations'


@admin.register(TranslationValue)
class TranslationValueAdmin(admin.ModelAdmin):
    list_display = ('key_name', 'language', 'value_preview', 'status', 'reviewed_by', 'updated_at')
    list_filter = ('language', 'status')
    search_fields = ('key__key', 'value')
    actions = ['mark_as_published', 'mark_as_draft', 'mark_as_in_review']

    def key_name(self, obj):
        return obj.key.key
    key_name.short_description = 'Key'

    def value_preview(self, obj):
        return (obj.value[:60] + '...') if len(obj.value) > 60 else obj.value
    value_preview.short_description = 'Translated Text'

    @admin.action(description='Mark selected translations as PUBLISHED')
    def mark_as_published(self, request, queryset):
        updated = queryset.update(status=TranslationValue.Status.PUBLISHED)
        # Bump version for all affected languages
        languages = set(queryset.values_list('language', flat=True))
        for lang in languages:
            TranslationVersion.bump(lang)
        self.message_user(request, f"{updated} translation(s) published successfully.")

    @admin.action(description='Mark selected translations as DRAFT')
    def mark_as_draft(self, request, queryset):
        updated = queryset.update(status=TranslationValue.Status.DRAFT)
        languages = set(queryset.values_list('language', flat=True))
        for lang in languages:
            TranslationVersion.bump(lang)
        self.message_user(request, f"{updated} translation(s) set to draft.")

    @admin.action(description='Mark selected translations as IN_REVIEW')
    def mark_as_in_review(self, request, queryset):
        queryset.update(status=TranslationValue.Status.IN_REVIEW)
        self.message_user(request, "Selected translation(s) moved to in review.")


@admin.register(TranslationVersion)
class TranslationVersionAdmin(admin.ModelAdmin):
    list_display = ('language', 'version', 'updated_at')
    readonly_fields = ('updated_at',)
    actions = ['bump_version']

    @admin.action(description='Bump version (invalidates app client cache)')
    def bump_version(self, request, queryset):
        for obj in queryset:
            obj.version += 1
            obj.save()
        self.message_user(request, "Version(s) bumped successfully.")

