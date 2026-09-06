from django.apps import AppConfig


class PsyInstituteConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.institutes.psy_institute"
    label = "psy_institute"
    verbose_name = "مؤسسه روان‌شناسی"

    def ready(self):
        # Role group names used by permissions.
        self.role_admin = "psy_admin"
        self.role_therapist = "psy_therapist"
        self.role_patient = "psy_patient"
