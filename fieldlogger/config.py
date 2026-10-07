"""Configuration loading for django-field-logger.

Reads the ``FIELD_LOGGER_SETTINGS`` dict from the Django settings and builds
a per-model logging configuration, resolving the ``logging_enabled``,
``fail_silently`` and ``callbacks`` options across the global, app and model
scopes.
"""

from typing import Any, Dict, FrozenSet, List, Tuple, Type, TypedDict, cast

from django.apps import apps
from django.db import models
from django.db.models import Model
from django.db.models.fields import Field
from django.utils.module_loading import import_string

from .app_settings import get_settings
from .callbacks import Callback

# Django >= 5.0 only; None on older versions.
GENERATED_FIELD = getattr(models, "GeneratedField", None)


class ModelConfig(TypedDict):
    """Resolved logging configuration of a single model."""

    logging_fields: FrozenSet[Field]
    logging_m2m_fields: FrozenSet[models.ManyToManyField]
    callbacks: List[Callback]
    fail_silently: bool


# Through model -> (model declaring the field, many-to-many field).
M2MConfig = Dict[Type[Model], Tuple[Type[Model], models.ManyToManyField]]


def through_model(field: models.ManyToManyField) -> Type[Model]:
    """Return the through model of ``field``; always resolved once the
    app registry is ready (``None`` or a string only in the stubs)."""
    return cast(Type[Model], field.remote_field.through)


def _is_loggable(field: Field) -> bool:
    """Whether a field can be logged on save: concrete (excludes private
    fields), with its own column (excludes many-to-many, which despite
    being "concrete" only has a through table) and not computed by the
    database (``GeneratedField`` values may be stale in memory)."""
    return bool(
        field.concrete
        and not field.many_to_many
        and not (GENERATED_FIELD and isinstance(field, GENERATED_FIELD))
    )


class LoggingConfig:
    """Lazily builds and caches the per-model logging configuration."""

    def __init__(self) -> None:
        self._settings: Dict[str, Any] = {}
        self._config: Dict[Type[Model], ModelConfig] = {}
        self._m2m_config: M2MConfig = {}
        self._loaded = False

    def _all_scopes(self, key: str, *configs: dict) -> bool:
        """Whether a boolean setting is enabled in the global scope and in
        every given scope; missing values default to enabled."""
        return self._settings.get(key.upper(), True) and all(
            config.get(key, True) for config in configs
        )

    def _logging_enabled(self, *configs: dict) -> bool:
        return self._all_scopes("logging_enabled", *configs)

    def _fail_silently(self, *configs: dict) -> bool:
        return self._all_scopes("fail_silently", *configs)

    def _callbacks(self, *configs: dict) -> List[Callback]:
        """Concatenate the callbacks of all scopes, importing dotted paths."""
        callbacks = list(self._settings.get("CALLBACKS", []))
        for config in configs:
            callbacks += config.get("callbacks", [])

        return [
            import_string(callback) if isinstance(callback, str) else callback
            for callback in callbacks
        ]

    def _logging_fields(
        self, model_class: Type[Model], model_settings: Dict[str, Any]
    ) -> Tuple[FrozenSet[Field], FrozenSet[models.ManyToManyField]]:
        """Resolve the ``fields``/``exclude_fields`` options to two sets of
        Field objects: regular fields and many-to-many fields."""
        fields = model_settings.get("fields", [])
        exclude_fields = set(model_settings.get("exclude_fields", []))

        logging_fields = set()
        logging_m2m_fields = set()
        for field in model_class._meta.get_fields():
            # Reverse relations (``ForeignObjectRel``) are not ``Field``s.
            if not isinstance(field, Field) or field.name in exclude_fields:
                continue
            if fields != "__all__" and field.name not in fields:
                continue

            # Forward many-to-many changes do not go through ``save()``, so
            # they are logged from the ``m2m_changed`` signal. An isinstance
            # check because ``field.concrete`` for many-to-many changed from
            # True to False in Django 6.0.
            if isinstance(field, models.ManyToManyField):
                logging_m2m_fields.add(field)
            elif _is_loggable(field):
                logging_fields.add(field)

        return frozenset(logging_fields), frozenset(logging_m2m_fields)

    def _build(self) -> None:
        self._settings = get_settings()

        for app, app_config in self._settings.get("LOGGING_APPS", {}).items():
            if not app_config or not self._logging_enabled(app_config):
                continue

            for model, model_config in app_config.get("models", {}).items():
                if not model_config or not self._logging_enabled(
                    app_config, model_config
                ):
                    continue

                try:
                    model_class = apps.get_model(app, model)
                except LookupError:
                    continue

                logging_fields, logging_m2m_fields = self._logging_fields(
                    model_class, model_config
                )

                self._config[model_class] = {
                    "logging_fields": logging_fields,
                    "logging_m2m_fields": logging_m2m_fields,
                    "callbacks": self._callbacks(app_config, model_config),
                    "fail_silently": self._fail_silently(app_config, model_config),
                }

                for field in logging_m2m_fields:
                    self._m2m_config[through_model(field)] = (
                        model_class,
                        field,
                    )

    def get_config(self) -> Dict[Type[Model], ModelConfig]:
        """Return the per-model configuration, building it on first access."""
        if not self._loaded:
            self._build()
            self._loaded = True

        return self._config

    def get_m2m_config(self) -> M2MConfig:
        """Map of through models to their (model, many-to-many field) pair,
        built together with the per-model configuration."""
        self.get_config()
        return self._m2m_config

    def invalidate(self) -> None:
        """Discard the cached configuration; rebuilt on next access."""
        self._config = {}
        self._m2m_config = {}
        self._loaded = False


_logging_config = LoggingConfig()
get_config = _logging_config.get_config
get_m2m_config = _logging_config.get_m2m_config
invalidate_config = _logging_config.invalidate
