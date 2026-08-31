import os
import json
from django.core.management.base import BaseCommand
from django.conf import settings
from apps.notifications.call_notifications import init_firebase_admin


class Command(BaseCommand):
    help = "Safely checks Firebase Admin SDK initialization status without displaying secrets."

    def handle(self, *args, **options):
        env_raw = os.getenv('FIREBASE_SERVICE_ACCOUNT_KEY') or os.getenv('FIREBASE_SERVICE_ACCOUNT_JSON') or getattr(settings, 'FIREBASE_SERVICE_ACCOUNT_KEY', None)
        gac_raw = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
        credentials_present = bool(env_raw or gac_raw)

        app = init_firebase_admin()
        firebase_initialized = bool(app)
        project_id = getattr(app, 'project_id', None) if app else None

        self.stdout.write(self.style.SUCCESS("--- FIREBASE DIAGNOSTIC REPORT ---"))
        self.stdout.write(f"credentials_present: {str(credentials_present).lower()}")
        self.stdout.write(f"firebase_initialized: {str(firebase_initialized).lower()}")
        self.stdout.write(f"project_id: {project_id if project_id else 'null'}")
