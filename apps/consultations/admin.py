from django.contrib import admin
from .models import Consultation, ConsultationNote, VideoSession

admin.site.register(Consultation)
admin.site.register(ConsultationNote)
admin.site.register(VideoSession)
