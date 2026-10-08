from django.apps import AppConfig


class FieldloggerConfig(AppConfig):
    # FieldLog declares its id; without this, Django >= 3.2 would warn
    # (models.W042) since the field is marked auto_created.
    default_auto_field = "django.db.models.BigAutoField"
    name = "fieldlogger"

    def ready(self) -> None:
        # Imported here because signals (and the configuration it loads)
        # need the app registry to be ready.
        from . import signals

        signals.connect_signals()
