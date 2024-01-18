from datetime import date, datetime, time, timedelta
from decimal import Decimal
from json import JSONEncoder, JSONDecoder

from django.conf import settings
from django.db import models
from django.utils.module_loading import import_string


SETTINGS = getattr(settings, "FIELD_LOGGER_SETTINGS", {})


class Encoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime, time)):
            return obj.isoformat()

        if isinstance(obj, timedelta):
            return obj.total_seconds()

        if isinstance(obj, Decimal):
            return float(obj)

        if isinstance(obj, (bytes, bytearray)):
            return obj.decode()

        if isinstance(obj, memoryview):
            return obj.tobytes().decode()

        if isinstance(obj, models.Model):
            return obj.pk

        if isinstance(obj, models.QuerySet):
            return list(obj.values_list("pk", flat=True))

        return super().default(obj)


class Decoder(JSONDecoder):
    pass


def logging_enabled(*configs):
    return SETTINGS.get("LOGGING_ENABLED", True) and all(
        config.get("logging_enabled", True) for config in configs
    )


def logging_fields(instance):
    model_config = LOGGING_CONFIG.get(instance._meta.label, {})
    logging_fields = model_config.get("fields", [])
    if not logging_fields:
        exclude_fields = model_config.get("exclude_fields", [])
        if exclude_fields:
            logging_fields = [
                field.name
                for field in instance._meta.fields
                if field.name not in exclude_fields
            ]

    return frozenset(logging_fields)


def callbacks(*configs):
    callbacks = SETTINGS.get("CALLBACKS", [])
    for config in configs:
        callbacks += config.get("callbacks", [])

    callbacks = map(
        lambda callback: import_string(callback)
        if isinstance(callback, str)
        else callback,
        callbacks,
    )

    return list(callbacks)


ENCODER = SETTINGS.get("ENCODER")
ENCODER = import_string(ENCODER) if ENCODER else Encoder

DECODER = SETTINGS.get("DECODER")
DECODER = import_string(DECODER) if DECODER else Decoder

LOGGING_APPS = SETTINGS.get("LOGGING_APPS", {})

LOGGING_CONFIG = {}
for app, app_config in LOGGING_APPS.items():
    if not app_config or not logging_enabled(SETTINGS, app_config):
        continue

    for model, model_config in app_config.get("models", {}).items():
        if not model_config or not logging_enabled(SETTINGS, app_config, model_config):
            continue

        model_config.update(
            {"callbacks": callbacks(SETTINGS, app_config, model_config)}
        )

        LOGGING_CONFIG[f"{app}.{model}"] = model_config
