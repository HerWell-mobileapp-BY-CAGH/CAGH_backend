import uuid
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from apps.notifications.models import DeviceToken
from apps.notifications.call_notifications import send_call_offer_push

User = get_user_model()


class Command(BaseCommand):
    help = "Dispatches a manual DATA-ONLY high-priority FCM call offer push notification to a user for isolation testing."

    def add_arguments(self, parser):
        parser.add_argument('--username', type=str, help='Target username to send test call push to')
        parser.add_argument('--token', type=str, help='Specific FCM device token to send push to')

    def handle(self, *args, **options):
        username = options.get('username')
        token_str = options.get('token')

        if not username and not token_str:
            self.stderr.write(self.style.ERROR("Please provide either --username or --token argument."))
            return

        target_user = None
        if username:
            target_user = User.objects.filter(username__iexact=username).first()
            if not target_user:
                self.stderr.write(self.style.ERROR(f"User with username '{username}' not found."))
                return

        if token_str:
            if not target_user:
                target_user = User.objects.first()
            DeviceToken.objects.update_or_create(
                token=token_str,
                defaults={'user': target_user, 'is_active': True}
            )
            self.stdout.write(self.style.SUCCESS(f"Registered/updated test token for user {target_user.username}."))

        tokens = DeviceToken.objects.filter(user=target_user, is_active=True)
        if not tokens.exists():
            self.stderr.write(self.style.ERROR(f"No active device tokens found for user '{target_user.username}'."))
            return

        self.stdout.write(self.style.NOTICE(f"Sending DATA-ONLY high-priority FCM call offer push to user '{target_user.username}' ({tokens.count()} token(s))..."))

        # Create dummy consultation object stub
        class DummyConsultation:
            id = uuid.uuid4()

        result = send_call_offer_push(
            caller=target_user,  # dummy self or sender
            recipient=target_user,
            consultation=DummyConsultation(),
            call_type="VOICE",
            session_key=f"TEST-{uuid.uuid4().hex[:8].upper()}",
            agora_channel_name="cagh_test_voice_channel",
            agora_app_id="cagh_test_agora_app_id",
        )

        self.stdout.write(self.style.SUCCESS(f"Successfully dispatched test call offer push notification to {target_user.username}!"))
