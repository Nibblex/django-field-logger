from django.apps import AppConfig


class FieldloggerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fieldlogger"

    def ready(self):
        import fieldlogger.signals  # noqa
