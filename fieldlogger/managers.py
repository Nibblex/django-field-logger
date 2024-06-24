from django.db import models

from .fieldlogger import log_fields as _log_fields
from .fieldlogger import run_callbacks


class FieldLoggerManager(models.Manager):
    def bulk_create(self, objs, log_fields: bool = True, **kwargs):
        instances = super().bulk_create(objs, **kwargs)
        if log_fields:
            from .config import LOGGING_CONFIG

            logging_config = LOGGING_CONFIG.get(self.model, {})
            logging_fields = logging_config.get("logging_fields", frozenset())
            callbacks = logging_config.get("callbacks", [])
            fail_silently = logging_config.get("fail_silently", False)

            for instance in instances:
                logs = _log_fields(instance, logging_fields)

                run_callbacks(instance, callbacks, logging_fields, logs, fail_silently)

        return instances
