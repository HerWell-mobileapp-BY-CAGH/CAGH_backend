from django.contrib import admin
from .models import ChatRoom, Message, Attachment

admin.site.register(ChatRoom)
admin.site.register(Message)
admin.site.register(Attachment)
