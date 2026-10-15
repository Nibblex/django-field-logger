from django.apps import AppConfig


class FieldloggerConfig(AppConfig):
    # The id of FieldLog, as in its migrations, whatever the project's
    # DEFAULT_AUTO_FIELD.
    default_auto_field = "django.db.models.BigAutoField"
    name = "fieldlogger"

    def ready(self) -> None:
        # Imported here because signals (and the configuration it loads)
        # need the app registry to be ready.
        from . import signals

        signals.connect_signals()
