from django.db import models

from .fieldlogger import log_fields as _log_fields


class FieldLoggerManager(models.Manager):
    def bulk_create(
        self, objs, log_fields: bool = True, run_callbacks: bool = True, **kwargs
    ):
        res = super().bulk_create(objs, **kwargs)
        if log_fields:
            _log_fields(self.model, objs, run_callbacks=run_callbacks)

        return res

    def bulk_update(
        self, objs, fields, log_fields: bool = True, run_callbacks: bool = True, **kwargs
    ):
        if log_fields:
            pre_instances = self.in_bulk([obj.pk for obj in objs])

        res = super().bulk_update(objs, fields, **kwargs)

        if log_fields:
            for obj in objs:
                obj._fieldlogger_pre_instance = pre_instances.get(obj.id)

            _log_fields(
                self.model, objs, update_fields=fields, run_callbacks=run_callbacks
            )

            for obj in objs:
                del obj._fieldlogger_pre_instance

        return res
