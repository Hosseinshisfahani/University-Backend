from django.apps import AppConfig


class PsyInstituteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.institutes.psy_institute"
    label = "psy_institute"
    verbose_name = "موسسه روانشناسی"

    def ready(self) -> None:
        from apps.kernel.tenancy.services import register_institute_adapter

        from .module_adapters import PsyAdapter
        from . import signals  # noqa: F401

        register_institute_adapter("psy", PsyAdapter())
