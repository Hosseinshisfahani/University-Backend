"""Private files live outside MEDIA_ROOT so /media/ cannot serve them.

Existing rows may still name a file under the public tree. Reads fall
back to that path until relocate_private_media moves the bytes.
"""

from pathlib import Path

from django.conf import settings
from django.core.files.storage import FileSystemStorage


class PrivateMediaStorage(FileSystemStorage):
    def __init__(self, **kwargs):
        location = kwargs.pop("location", None) or settings.PRIVATE_MEDIA_ROOT
        super().__init__(location=str(location), base_url=None, **kwargs)

    def deconstruct(self):
        return ("apps.kernel.core.storage.PrivateMediaStorage", [], {})

    def url(self, name):
        raise ValueError("Private files have no public URL.")

    def _legacy(self, name: str) -> Path:
        return Path(settings.MEDIA_ROOT) / name

    def _private(self, name: str) -> Path:
        return Path(self.location) / name

    def exists(self, name):
        return self._private(name).exists() or self._legacy(name).is_file()

    def open(self, name, mode="rb"):
        private = self._private(name)
        if private.exists():
            return private.open(mode)
        legacy = self._legacy(name)
        if legacy.is_file():
            return legacy.open(mode)
        return private.open(mode)

    def path(self, name):
        private = self._private(name)
        if private.exists():
            return str(private)
        legacy = self._legacy(name)
        if legacy.is_file():
            return str(legacy)
        return str(private)


private_media_storage = PrivateMediaStorage()
