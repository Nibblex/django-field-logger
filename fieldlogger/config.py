from functools import reduce
from typing import Any, Dict, FrozenSet, List, Union

from django import VERSION
from django.apps import apps
from django.conf import settings
from django.db import connection
from django.db.models.fields import Field
from django.utils.module_loading import import_string

from .models import Callback, LoggableModel

DB_ENGINE = connection.vendor
if DB_ENGINE == "sqlite":
    DB_VERSION = connection.Database.sqlite_version_info
elif DB_ENGINE == "mysql":
    DB_VERSION = connection.Database.mysql_version
else:
    DB_VERSION = None

DB_COMPATIBLE = VERSION >= (4, 0) and (
    DB_ENGINE == "postgresql"
    or (DB_ENGINE == "mysql" and DB_VERSION >= (10, 5))
    or (DB_ENGINE == "sqlite" and DB_VERSION >= (3, 35))
)


class LoggingConfig:
    __config = {}

    def __init__(self):
        self.__settings = getattr(settings, "FIELD_LOGGER_SETTINGS", {})

    def __cfg_reduce(self, op, key, *configs, default=None):
        return reduce(
            op,
            [config.get(key, default) for config in configs],
            self.__settings.get(key.upper(), default),
        )

    def __logging_enabled(self, *configs: Dict[str, bool]) -> bool:
        return self.__cfg_reduce(
            lambda a, b: a and b, "logging_enabled", *configs, default=True
        )

    def __logging_fields(
        self, model_class: LoggableModel, model_config: Dict[str, Any]
    ) -> FrozenSet[Field]:
        fields = model_config.get("fields", [])
        exclude_fields = set(model_config.get("exclude_fields", []))
        model_fields = model_class._meta.get_fields()

        if fields == "__all__":
            return frozenset(
                field for field in model_fields if field.name not in exclude_fields
            )

        return frozenset(
            field for field in model_fields if field.name in set(fields) - exclude_fields
        )

    def __callbacks(
        self, *configs: Dict[str, List[Union[str, Callback]]]
    ) -> List[Callback]:
        callbacks = self.__cfg_reduce(
            lambda a, b: a + b, "callbacks", *configs, default=[]
        )

        callbacks = [
            import_string(callback) if isinstance(callback, str) else callback
            for callback in callbacks
        ]

        return callbacks

    def __fail_silently(self, *configs: Dict[str, bool]) -> bool:
        return self.__cfg_reduce(
            lambda a, b: a and b, "fail_silently", *configs, default=True
        )

    def __set_config(self):
        for app, app_config in self.__settings.get("LOGGING_APPS", {}).items():
            if not app_config or not self.__logging_enabled(app_config):
                continue

            for model, model_config in app_config.get("models", {}).items():
                if not model_config or not self.__logging_enabled(
                    app_config, model_config
                ):
                    continue

                try:
                    model_class = apps.get_model(app, model)
                except LookupError:
                    continue

                self.__config[model_class] = {
                    "logging_fields": self.__logging_fields(model_class, model_config),
                    "callbacks": self.__callbacks(app_config, model_config),
                    "fail_silently": self.__fail_silently(app_config, model_config),
                }

    def get_config(self):
        if not self.__config:
            self.__set_config()

        return self.__config

    def __iter__(self):
        return iter(self.__config)

    def __getitem__(self, model_class: LoggableModel):
        return self.__config.get(model_class, {})


get_config = LoggingConfig().get_config
