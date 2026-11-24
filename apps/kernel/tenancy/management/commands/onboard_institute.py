"""Create an inactive institute and an initial admin membership.

Activation stays a separate domain and readiness step. This command does
not copy a backend and does not enable unknown modules.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.kernel.tenancy.models import Institute
from apps.kernel.tenancy.registry import validate_enabled_modules
from apps.kernel.tenancy.services import grant_roles

User = get_user_model()


class Command(BaseCommand):
    help = "Create an inactive standard institute and grant an admin membership."

    def add_arguments(self, parser):
        parser.add_argument("--slug", required=True)
        parser.add_argument("--name", required=True)
        parser.add_argument("--modules", default="content")
        parser.add_argument("--admin-username", default="")
        parser.add_argument("--frontend-mode", default=Institute.FrontendMode.STANDARD)

    def handle(self, *args, **options):
        slug = options["slug"].strip()
        modules = [item.strip() for item in options["modules"].split(",") if item.strip()]
        try:
            validate_enabled_modules(slug, modules)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        if options["frontend_mode"] not in Institute.FrontendMode.values:
            raise CommandError("frontend mode must be standard or custom")
        institute, created = Institute.objects.get_or_create(
            slug=slug,
            defaults={
                "name": options["name"],
                "is_active": False,
                "frontend_mode": options["frontend_mode"],
                "enabled_modules": modules,
            },
        )
        if not created:
            raise CommandError(f"institute {slug} already exists")
        username = options["admin_username"]
        if username:
            user = User.objects.filter(username=username).first()
            if user is None:
                raise CommandError(f"user {username} was not found")
            grant_roles(
                user=user,
                institute=institute,
                roles=["admin"],
                allow_inactive=True,
            )
        self.stdout.write(
            f"onboarded inactive institute {slug} modules={','.join(modules)}"
        )
