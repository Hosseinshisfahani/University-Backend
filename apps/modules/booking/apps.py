from django.apps import AppConfig


class BookingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.booking"
    label = "booking"
    verbose_name = "نوبت‌دهی"

    def ready(self) -> None:
        from apps.kernel.finance.checkout import register_checkout

        from .services.booking import fulfill_appointment_checkout, release_appointment_checkout

        register_checkout(
            "booking.appointment:",
            fulfill_appointment_checkout,
            release_appointment_checkout,
        )
