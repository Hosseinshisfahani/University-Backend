"""Confirm a DNS TXT challenge for `_university-verify.<hostname>`.

Pass the TXT value with --token. --lookup runs `dig` when it is installed
and does not require a DNS library.
"""

import subprocess

from django.core.management.base import BaseCommand, CommandError

from apps.kernel.tenancy.domains import DomainError, confirm_verification


class Command(BaseCommand):
    help = "Consume a domain ownership TXT challenge."

    def add_arguments(self, parser):
        parser.add_argument("--hostname", required=True)
        parser.add_argument("--token", default="")
        parser.add_argument("--lookup", action="store_true")

    def handle(self, *args, **options):
        token = options["token"]
        hostname = options["hostname"]
        if options["lookup"]:
            name = f"_university-verify.{hostname.strip().rstrip('.')}"
            try:
                completed = subprocess.run(
                    ["dig", "+short", "TXT", name],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise CommandError(f"TXT lookup failed: {exc}") from exc
            token = completed.stdout.strip().strip('"')
            if not token:
                raise CommandError(f"no TXT record at {name}")
        if not token:
            raise CommandError("pass --token or --lookup")
        try:
            domain = confirm_verification(hostname=hostname, token=token)
        except DomainError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"verified {domain.hostname}")
