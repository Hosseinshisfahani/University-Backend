from django.apps import AppConfig


class ShopConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.modules.shop"
    label = "shop"
    verbose_name = "فروشگاه"

    def ready(self) -> None:
        from apps.kernel.finance.checkout import register_checkout

        from .services import fulfill_shop_checkout, release_shop_checkout

        register_checkout("shop.order:", fulfill_shop_checkout, release_shop_checkout)
        register_checkout("psy.order:", fulfill_shop_checkout, release_shop_checkout)
