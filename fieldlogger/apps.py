from django.apps import AppConfig


class FieldloggerConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "fieldlogger"

    def ready(self):
        # Imported here because signals (and the configuration it loads)
        # need the app registry to be ready.
        from . import signals

        signals.connect_signals()
