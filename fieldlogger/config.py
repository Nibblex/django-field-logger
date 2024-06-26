from functools import reduce
from typing import Any, Dict, FrozenSet, List, Union

from django.apps import apps
from django.conf import settings
from django.utils.module_loading import import_string

from .models import Callback, LoggableModel

SETTINGS = getattr(settings, "FIELD_LOGGER_SETTINGS", {})


def _cfg_reduce(op, key, *configs, default=None):
    return reduce(
        op,
        [config.get(key, default) for config in configs],
        SETTINGS.get(key.upper(), default),
    )


def _logging_enabled(*configs: Dict[str, bool]) -> bool:
    return _cfg_reduce(lambda a, b: a and b, "logging_enabled", *configs, default=True)


def _fail_silently(*configs: Dict[str, bool]) -> bool:
    return _cfg_reduce(lambda a, b: a and b, "fail_silently", *configs, default=True)


def _callbacks(*configs: Dict[str, List[Union[str, Callback]]]) -> List[Callback]:
    callbacks = _cfg_reduce(lambda a, b: a + b, "callbacks", *configs, default=[])

    callbacks = [
        import_string(callback) if isinstance(callback, str) else callback
        for callback in callbacks
    ]

    return callbacks


def _logging_fields(
    model_class: LoggableModel, model_config: Dict[str, Any]
) -> FrozenSet[str]:
    fields = model_config.get("fields", [])
    exclude_fields = model_config.get("exclude_fields", [])
    model_fields = [field.name for field in model_class._meta.fields]

    return frozenset(model_fields if fields == "__all__" else fields) - frozenset(
        exclude_fields
    )


LOGGING_CONFIG = {}
for app, app_config in SETTINGS.get("LOGGING_APPS", {}).items():
    if not app_config or not _logging_enabled(app_config):
        continue

    for model, model_config in app_config.get("models", {}).items():
        if not model_config or not _logging_enabled(app_config, model_config):
            continue

        try:
            model_class = apps.get_model(app, model)
        except LookupError:
            continue

        LOGGING_CONFIG[f"{app}.{model}"] = {
            "fail_silently": _fail_silently(app_config, model_config),
            "callbacks": _callbacks(app_config, model_config),
            "logging_fields": _logging_fields(model_class, model_config),
        }
