from django.conf import settings
from django.core.checks import Error, register


@register()
def vandar_production_check(app_configs, **kwargs):
    if app_configs is not None and not any(
        config.label == "finance" for config in app_configs
    ):
        return []
    errors = []
    sandbox = bool(getattr(settings, "VANDAR_SANDBOX_MODE", True))
    allow = bool(getattr(settings, "VANDAR_ALLOW_SANDBOX", False))
    if not settings.DEBUG and sandbox and not allow:
        errors.append(
            Error(
                "VANDAR_SANDBOX_MODE is on while DEBUG is off.",
                hint="Set VANDAR_SANDBOX_MODE=false, or VANDAR_ALLOW_SANDBOX=true for a deliberate sandbox deploy.",
                id="finance.E001",
            )
        )
    callback = getattr(settings, "VANDAR_CALLBACK_URL", "") or ""
    if callback and not callback.startswith("https://"):
        errors.append(
            Error(
                "VANDAR_CALLBACK_URL must use https.",
                hint="Register an https callback in the Vandar panel and set VANDAR_CALLBACK_URL to it.",
                id="finance.E002",
            )
        )
    if not settings.DEBUG and not sandbox and not callback.startswith("https://"):
        errors.append(
            Error(
                "Live Vandar mode requires an https VANDAR_CALLBACK_URL.",
                hint="Set VANDAR_CALLBACK_URL to the https URL registered in the Vandar panel.",
                id="finance.E003",
            )
        )
    return errors
