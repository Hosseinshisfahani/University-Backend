from django.apps import AppConfig


class TenancyConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.kernel.tenancy"
    label = "tenancy"
    verbose_name = "مراکز"

    def ready(self) -> None:
        from . import signals  # noqa: F401
