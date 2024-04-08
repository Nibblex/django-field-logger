from datetime import date, datetime, time, timedelta
from decimal import Decimal
from functools import reduce
from json import JSONDecoder, JSONEncoder
from uuid import UUID

from django.conf import settings
from django.core.files import File
from django.db import models
from django.utils.module_loading import import_string

SETTINGS = getattr(settings, "FIELD_LOGGER_SETTINGS", {}).copy()


class Encoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime, time)):
            return obj.isoformat()
        elif isinstance(obj, timedelta):
            return str(obj.total_seconds())
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, (bytes, bytearray)):
            return obj.decode()
        elif isinstance(obj, memoryview):
            return obj.tobytes().decode()
        elif isinstance(obj, File):
            return obj.name
        elif isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, models.Model):
            return obj.pk
        elif isinstance(obj, models.QuerySet):
            return list(obj.values_list("pk", flat=True))

        return super().default(obj)


class Decoder(JSONDecoder):
    pass


def _cfg_reduce(op, key, *configs, default=None):
    return reduce(
        op,
        [config.get(key, default) for config in configs],
        SETTINGS.get(key.upper(), default),
    )


def logging_enabled(*configs):
    return _cfg_reduce(lambda a, b: a and b, "logging_enabled", *configs, default=True)


def fail_silently(*configs):
    return _cfg_reduce(lambda a, b: a and b, "fail_silently", *configs, default=True)


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
    callbacks = _cfg_reduce(lambda a, b: a + b, "callbacks", *configs, default=[])

    callbacks = [
        import_string(callback) if isinstance(callback, str) else callback
        for callback in callbacks
    ]

    return callbacks


ENCODER = SETTINGS.get("ENCODER")
ENCODER = import_string(ENCODER) if ENCODER else Encoder

DECODER = SETTINGS.get("DECODER")
DECODER = import_string(DECODER) if DECODER else Decoder

LOGGING_CONFIG = {}
for app, app_config in SETTINGS.get("LOGGING_APPS", {}).items():
    if not app_config or not logging_enabled(app_config):
        continue

    for model, model_config in app_config.get("models", {}).items():
        if not model_config or not logging_enabled(app_config, model_config):
            continue

        model_config["callbacks"] = callbacks(app_config, model_config)
        model_config["fail_silently"] = fail_silently(app_config, model_config)

        LOGGING_CONFIG[f"{app}.{model}"] = model_config
