from django.apps import AppConfig


class ShopConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.shop"
    label = "shop"
    verbose_name = "فروشگاه"

    def ready(self) -> None:
        from . import signals  # noqa: F401
