from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Profile, EmergencyContact, SOSLog, UserPreference


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'role', 'phone_number', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_superuser')
    fieldsets = BaseUserAdmin.fieldsets + (
        ('CAGH Roles & Info', {'fields': ('role', 'phone_number')}),
    )


admin.site.register(Profile)
admin.site.register(EmergencyContact)
admin.site.register(SOSLog)
admin.site.register(UserPreference)
