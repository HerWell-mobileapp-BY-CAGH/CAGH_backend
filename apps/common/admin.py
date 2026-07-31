from django.contrib import admin
from .models import Facility, AuditLog, Report

admin.site.register(Facility)
admin.site.register(AuditLog)
admin.site.register(Report)
