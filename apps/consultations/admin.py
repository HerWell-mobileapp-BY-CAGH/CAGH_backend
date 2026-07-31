from django.contrib import admin
from .models import Consultation, ConsultationNote, VoiceSession, VideoSession

admin.site.register(Consultation)
admin.site.register(ConsultationNote)
admin.site.register(VoiceSession)
admin.site.register(VideoSession)
