# University Services domain

Core university operational services.

This is a domain namespace — each concrete service becomes its own Django
app inside this package (e.g. `apps.university_services.<service>`), with
its own `models.py`, `serializers.py`, `views.py`, and `urls.py`.

To add an app here:

1. Create the app package with an `AppConfig` where
   `name = "apps.university_services.<service>"`.
2. Register it in `LOCAL_APPS` in `config/settings/base.py`.
3. Mount its urls under `/api/v1/` in `config/urls.py`.

Detailed services, features, and relations for this domain will be
specified in upcoming steps.
