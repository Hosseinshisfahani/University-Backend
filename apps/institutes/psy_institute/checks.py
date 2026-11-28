from django.apps import apps
from django.contrib import admin
from django.core.checks import Error, Tags, register

from .legacy import FROZEN_MODEL_NAMES


@register(Tags.admin)
def frozen_legacy_models_are_not_in_admin(app_configs, **kwargs):
    if app_configs is not None and not any(config.label == "psy_institute" for config in app_configs):
        return []
    errors = []
    for name in FROZEN_MODEL_NAMES:
        model = apps.get_model("psy_institute", name)
        if admin.site.is_registered(model):
            errors.append(
                Error(
                    f"{model._meta.label} is registered in Django admin.",
                    hint="Register the shared module model. This psychology model is frozen history.",
                    obj=model,
                    id="psy_institute.E001",
                )
            )
    return errors
