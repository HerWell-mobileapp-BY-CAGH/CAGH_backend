import os
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.db.models import Q
from django.core.exceptions import ValidationError

User = get_user_model()


class Command(BaseCommand):
    help = "Creates or resets the administrator using ADMIN_USERNAME, ADMIN_EMAIL, and ADMIN_PASSWORD environment variables."

    def handle(self, *args, **options):
        username = os.environ.get("ADMIN_USERNAME", "").strip()
        email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("ADMIN_PASSWORD", "")

        missing = [
            name for name, value in (
                ("ADMIN_USERNAME", username),
                ("ADMIN_EMAIL", email),
                ("ADMIN_PASSWORD", password),
            ) if not value
        ]
        if missing:
            raise CommandError(
                "Set these environment variables before provisioning an admin: "
                + ", ".join(missing)
            )

        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError("ADMIN_PASSWORD is not acceptable: " + "; ".join(exc.messages))

        user = User.objects.filter(
            Q(username__iexact=username) | Q(email__iexact=email)
        ).first()

        created = False
        if user is None:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                role=User.Role.ADMIN if hasattr(User, "Role") else "ADMIN",
                is_staff=True,
                is_superuser=True,
            )
            created = True
        else:
            user.username = username
            user.email = email
            user.is_staff = True
            user.is_superuser = True
            if hasattr(user, "Role"):
                user.role = User.Role.ADMIN
            user.set_password(password)
            user.save()

        action = "Created" if created else "Reset"
        self.stdout.write(self.style.SUCCESS(f"Successfully {action} admin user '{username}' ({email})."))
