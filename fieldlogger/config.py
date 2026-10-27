"""Configuration loading for django-field-logger.

Reads the ``FIELD_LOGGER_SETTINGS`` dict from the Django settings and builds
a per-model logging configuration, resolving the options that apply across
the global, app and model scopes: the switches ``logging_enabled``,
``fail_silently``, ``log_actor`` and ``log_remote_addr``, the ``callbacks``
and ``mask_fields`` of every scope, and the most specific ``mask_callable``
and ``log_deletions``.
"""

from collections.abc import Callable
from typing import Any, TypedDict, cast

from django.apps import apps
from django.db import models
from django.db.models import Model
from django.db.models.fields import Field
from django.utils.module_loading import import_string

from .app_settings import get_settings
from .callbacks import Callback
from .masking import mask_value

# Django >= 5.0 only; None on older versions.
GENERATED_FIELD = getattr(models, "GeneratedField", None)


class ModelConfig(TypedDict):
    """Resolved logging configuration of a single model."""

    logging_fields: frozenset[Field]
    logging_m2m_fields: frozenset[models.ManyToManyField]
    callbacks: list[Callback]
    fail_silently: bool
    # Whether the logs record who made the change (see set_actor()).
    log_actor: bool
    log_remote_addr: bool
    # Names of the fields whose logged values are masked, and the function
    # that masks them.
    mask_fields: frozenset[str]
    mask: Callable[[Any], Any]
    # Whether deletions are logged; off unless a scope turns it on.
    log_deletions: bool


# Through model -> (model declaring the field, many-to-many field).
M2MConfig = dict[type[Model], tuple[type[Model], models.ManyToManyField]]


def through_model(field: models.ManyToManyField) -> type[Model]:
    """Return the through model of ``field``; always resolved once the
    app registry is ready (``None`` or a string only in the stubs)."""
    return cast(type[Model], field.remote_field.through)


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
        self._settings: dict[str, Any] = {}
        self._config: dict[type[Model], ModelConfig] = {}
        self._m2m_config: M2MConfig = {}
        self._loaded = False

    def _all_scopes(self, key: str, *configs: dict) -> bool:
        """Whether a boolean setting is enabled in the global scope and in
        every given scope; missing values default to enabled."""
        return self._settings.get(key.upper(), True) and all(
            config.get(key, True) for config in configs
        )

    def _most_specific(self, key: str, *configs: dict, default: Any = None) -> Any:
        """The value of a setting in the most specific scope that sets it,
        even to a false value; ``default`` if none does."""
        for config in reversed(configs):
            if key in config:
                return config[key]
        return self._settings.get(key.upper(), default)

    def _mask_fields(self, *configs: dict) -> frozenset[str]:
        """The names in ``mask_fields`` of every scope."""
        names = set(self._settings.get("MASK_FIELDS", []))
        for config in configs:
            names.update(config.get("mask_fields", []))
        return frozenset(names)

    def _mask(self, *configs: dict) -> Callable[[Any], Any]:
        """The ``mask_callable`` of the most specific scope that sets one,
        importing a dotted path; ``mask_value`` if none does."""
        candidates = [config.get("mask_callable") for config in reversed(configs)]
        candidates.append(self._settings.get("MASK_CALLABLE"))
        mask = next((candidate for candidate in candidates if candidate), mask_value)
        return import_string(mask) if isinstance(mask, str) else mask

    def _callbacks(self, *configs: dict) -> list[Callback]:
        """Concatenate the callbacks of all scopes, importing dotted paths."""
        callbacks = list(self._settings.get("CALLBACKS", []))
        for config in configs:
            callbacks += config.get("callbacks", [])

        return [
            import_string(callback) if isinstance(callback, str) else callback
            for callback in callbacks
        ]

    def _logging_fields(
        self, model_class: type[Model], model_settings: dict[str, Any]
    ) -> tuple[frozenset[Field], frozenset[models.ManyToManyField]]:
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
            if not app_config or not self._all_scopes("logging_enabled", app_config):
                continue

            for model, model_config in app_config.get("models", {}).items():
                scopes = (app_config, model_config)
                if not model_config or not self._all_scopes("logging_enabled", *scopes):
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
                    "callbacks": self._callbacks(*scopes),
                    "fail_silently": self._all_scopes("fail_silently", *scopes),
                    "log_actor": self._all_scopes("log_actor", *scopes),
                    "log_remote_addr": self._all_scopes("log_remote_addr", *scopes),
                    "mask_fields": self._mask_fields(*scopes),
                    "mask": self._mask(*scopes),
                    "log_deletions": bool(
                        self._most_specific("log_deletions", *scopes, default=False)
                    ),
                }

                for field in logging_m2m_fields:
                    self._m2m_config[through_model(field)] = (model_class, field)

    def get_config(self) -> dict[type[Model], ModelConfig]:
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
