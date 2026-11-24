from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.kernel.finance"
    label = "finance"
    verbose_name = "مالی"
