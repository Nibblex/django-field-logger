from functools import reduce
from typing import Any, Dict, FrozenSet, List, Union

from django.apps import apps
from django.conf import settings
from django.utils.module_loading import import_string

from .models import Callback, LoggableModel
from .utils import getrmodel

SETTINGS = getattr(settings, "FIELD_LOGGER_SETTINGS", {})
LOGGING_APPS = SETTINGS.get("LOGGING_APPS", {})


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
    return [
        import_string(callback) if isinstance(callback, str) else callback
        for callback in _cfg_reduce(lambda a, b: a + b, "callbacks", *configs, default=[])
    ]


def _normalize_fields(fields: List[str]) -> FrozenSet[str]:
    return frozenset(field.replace(" ", "").replace(".", "__") for field in fields)


def _logging_fields(
    model_class: LoggableModel, model_config: Dict[str, Any]
) -> FrozenSet[str]:
    model_fields = frozenset(field.name for field in model_class._meta.fields)
    fields = model_config.get("fields", [])
    fields = model_fields if fields == "__all__" else _normalize_fields(fields)
    exclude_fields = _normalize_fields(model_config.get("exclude_fields", []))

    return (fields & model_fields) - exclude_fields


def _related_fields(
    model_class: LoggableModel, model_config: Dict[str, Any]
) -> FrozenSet[str]:
    related_fields = frozenset()

    for rfield in _normalize_fields(model_config.get("related_fields", [])):
        fieldpath, _, field = rfield.rpartition("__")

        cls = getrmodel(model_class, fieldpath)
        if not cls or not hasattr(cls, field):
            continue

        related_fields |= frozenset({(cls, fieldpath, field)})

    return related_fields


LOGGING_CONFIG = {}
for app, app_config in LOGGING_APPS.items():
    if not app_config or not _logging_enabled(app_config):
        continue

    for model, model_config in app_config.get("models", {}).items():
        if not model_config or not _logging_enabled(app_config, model_config):
            continue

        try:
            model_class = apps.get_model(app, model)
        except LookupError:
            continue

        LOGGING_CONFIG.setdefault(model_class, {"_related_fields": frozenset()}).update(
            {
                "logging_fields": _logging_fields(model_class, model_config),
                "callbacks": _callbacks(app_config, model_config),
                "fail_silently": _fail_silently(app_config, model_config),
            }
        )

        for cls, fieldpath, field in _related_fields(model_class, model_config):
            rapp_config = LOGGING_APPS.get(cls._meta.app_label, {})

            rlogging_cfg = LOGGING_CONFIG.setdefault(
                cls,
                {
                    "callbacks": _callbacks(rapp_config),
                    "fail_silently": _fail_silently(rapp_config),
                    "_related_fields": frozenset(),
                },
            )

            rlogging_cfg["_related_fields"] |= frozenset(
                {(model_class, fieldpath, field)}
            )
