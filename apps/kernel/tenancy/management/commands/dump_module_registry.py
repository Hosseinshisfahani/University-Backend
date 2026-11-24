import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.kernel.tenancy.registry import MODULES

CONTRACT = Path(settings.BASE_DIR) / "module-registry.json"


def contract_payload() -> dict:
    return {
        "modules": [
            {
                "id": item["id"],
                "prefix": item["prefix"],
                "ready": item["ready"],
                "legacy_prefixes": list(item["legacy_prefixes"]),
            }
            for item in MODULES
        ]
    }


class Command(BaseCommand):
    help = "Write module-registry.json, or check that the committed file matches the code."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true")

    def handle(self, *args, **options):
        payload = contract_payload()
        rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        if options["check"]:
            if not CONTRACT.exists():
                raise CommandError(f"missing {CONTRACT}")
            current = CONTRACT.read_text(encoding="utf-8")
            if current != rendered:
                raise CommandError("module-registry.json is stale. Re-run dump_module_registry.")
            self.stdout.write("module-registry.json matches the registry.")
            return
        CONTRACT.write_text(rendered, encoding="utf-8")
        self.stdout.write(f"wrote {CONTRACT}")
