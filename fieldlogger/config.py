from functools import reduce
from typing import Dict, FrozenSet, List, Union

from django.conf import settings
from django.utils.module_loading import import_string

from .models import Callback, LoggableModel

SETTINGS = getattr(settings, "FIELD_LOGGER_SETTINGS", {}).copy()


def _cfg_reduce(op, key, *configs, default=None):
    return reduce(
        op,
        [config.get(key, default) for config in configs],
        SETTINGS.get(key.upper(), default),
    )


def logging_enabled(*configs: Dict[str, bool]) -> bool:
    return _cfg_reduce(lambda a, b: a and b, "logging_enabled", *configs, default=True)


def fail_silently(*configs: Dict[str, bool]) -> bool:
    return _cfg_reduce(lambda a, b: a and b, "fail_silently", *configs, default=True)


def callbacks(*configs: Dict[str, List[Union[str, Callback]]]) -> List[Callback]:
    callbacks = _cfg_reduce(lambda a, b: a + b, "callbacks", *configs, default=[])

    callbacks = [
        import_string(callback) if isinstance(callback, str) else callback
        for callback in callbacks
    ]

    return callbacks


def logging_fields(instance: LoggableModel) -> FrozenSet[str]:
    model_config = LOGGING_CONFIG.get(instance._meta.label, {})

    exclude_fields = model_config.get("exclude_fields", [])
    if not exclude_fields:
        return frozenset(model_config.get("fields", []))

    return frozenset(
        field.name for field in instance._meta.fields if field.name not in exclude_fields
    )


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
