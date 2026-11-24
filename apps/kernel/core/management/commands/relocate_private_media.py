"""Move paid files and certificates out of the public media tree.

Prints a sha256 for each moved file. A second run leaves files that are
already in the private root.
"""

import hashlib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

PRIVATE_PREFIXES = (
    "shop/",
    "lms/",
    "psy/shop/files/",
    "psy/certificates/",
)


def _private_name(relative: str) -> bool:
    if relative.startswith("psy/shop/files/") or relative.startswith("psy/certificates/"):
        return True
    parts = relative.split("/")
    if len(parts) >= 3 and parts[0] in {"shop", "lms"} and (
        parts[2].startswith("files") or parts[2] == "certificates" or "/certificates/" in relative
    ):
        return True
    return False


class Command(BaseCommand):
    help = "Copy private media bytes out of MEDIA_ROOT and record their hashes."

    def handle(self, *args, **options):
        public = Path(settings.MEDIA_ROOT)
        private = Path(settings.PRIVATE_MEDIA_ROOT)
        private.mkdir(parents=True, exist_ok=True)
        moved = 0
        if not public.exists():
            self.stdout.write("no public media directory")
            return
        for path in public.rglob("*"):
            if not path.is_file():
                continue
            relative = path.relative_to(public).as_posix()
            if not relative.startswith(PRIVATE_PREFIXES) or not _private_name(relative):
                continue
            target = private / relative
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if target.exists():
                self.stdout.write(f"kept {relative} sha256={digest}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                target.unlink()
                raise RuntimeError(f"hash mismatch for {relative}")
            path.unlink()
            moved += 1
            self.stdout.write(f"moved {relative} sha256={digest}")
        self.stdout.write(f"private media moved={moved}")
