from django.contrib import admin
from .models import Hospital, MidwifeProfile, Qualification, Certificate, Expertise, SavedMidwife

admin.site.register(Hospital)
admin.site.register(MidwifeProfile)
admin.site.register(Qualification)
admin.site.register(Certificate)
admin.site.register(Expertise)
admin.site.register(SavedMidwife)
