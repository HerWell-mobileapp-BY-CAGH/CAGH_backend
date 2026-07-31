from django.contrib import admin
from .models import Availability, TimeSlot, Appointment

admin.site.register(Availability)
admin.site.register(TimeSlot)
admin.site.register(Appointment)
