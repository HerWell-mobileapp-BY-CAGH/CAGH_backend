import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Creates or resets the admin superuser using ADMIN_USERNAME, ADMIN_EMAIL, and ADMIN_PASSWORD environment variables."

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME", "admin")
        email = os.environ.get("ADMIN_EMAIL", "admin@cagh.org")
        password = os.environ.get("ADMIN_PASSWORD", "AdminPass123!")

        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "email": email,
                "role": User.Role.ADMIN if hasattr(User, "Role") else "ADMIN",
                "is_staff": True,
                "is_superuser": True,
            },
        )

        user.email = email
        user.is_staff = True
        user.is_superuser = True
        if hasattr(user, "Role"):
            user.role = User.Role.ADMIN
        user.set_password(password)
        user.save()

        action = "Created" if created else "Reset"
        self.stdout.write(self.style.SUCCESS(f"Successfully {action} admin user '{username}' ({email})."))
