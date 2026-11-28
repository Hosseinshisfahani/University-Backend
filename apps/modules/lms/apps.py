from django.apps import AppConfig


class LmsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.lms"
    label = "lms"
    verbose_name = "آموزش"

    def ready(self) -> None:
        from apps.kernel.finance.checkout import register_checkout

        from . import signals  # noqa: F401
        from .services import fulfill_enrollment_checkout, release_enrollment_checkout

        register_checkout(
            "lms.enrollment:",
            fulfill_enrollment_checkout,
            release_enrollment_checkout,
        )
