from django.db import models

from .fieldlogger import log_fields as _log_fields


class FieldLoggerManager(models.Manager):
    def bulk_create(
        self, objs, log_fields: bool = True, run_callbacks: bool = True, **kwargs
    ):
        instances = super().bulk_create(objs, **kwargs)
        if log_fields:
            _log_fields(self.model, instances, run_callbacks=run_callbacks)

        return instances
