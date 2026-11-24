from django.apps import AppConfig


class LmsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.lms"
    label = "lms"
    verbose_name = "آموزش"

    def ready(self) -> None:
        from . import signals  # noqa: F401
