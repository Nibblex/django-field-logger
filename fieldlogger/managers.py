"""Manager that adds field logging to bulk operations."""

from django.db import models

from .config import get_config
from .fieldlogger import db_supports_returning_pks, set_primary_keys
from .fieldlogger import log_fields as _log_fields


class FieldLoggerManager(models.Manager):
    """Logs field changes on ``bulk_create`` and ``bulk_update``.

    Both methods accept two extra keyword arguments: ``log_fields`` to
    disable logging for the call, and ``run_callbacks`` to skip the
    configured callbacks.
    """

    def bulk_create(
        self, objs, log_fields: bool = True, run_callbacks: bool = True, **kwargs
    ):
        # With ignore_conflicts, or on databases that cannot return primary
        # keys from bulk inserts, pks must be assigned manually so the logs
        # can reference their instances.
        if isinstance(self.model._meta.pk, models.AutoField) and (
            kwargs.get("ignore_conflicts", False)
            or not db_supports_returning_pks(self.model, using=self.db)
        ):
            set_primary_keys(objs, self.model, using=self.db)

        res = super().bulk_create(objs, **kwargs)

        if log_fields:
            logged_objs = objs
            if kwargs.get("ignore_conflicts", False):
                # Rows that conflicted were not inserted; do not log them.
                inserted_pks = set(
                    self.model._base_manager.using(self.db)
                    .filter(pk__in=[obj.pk for obj in objs])
                    .values_list("pk", flat=True)
                )
                logged_objs = [obj for obj in objs if obj.pk in inserted_pks]

            _log_fields(self.model, logged_objs, run_callbacks=run_callbacks)

        return res

    def bulk_update(
        self,
        objs,
        fields,
        log_fields: bool = True,
        run_callbacks: bool = True,
        **kwargs,
    ):
        logging_config = get_config().get(self.model)
        if not log_fields or logging_config is None:
            return super().bulk_update(objs, fields, **kwargs)

        # Only the logged fields are compared, so only they are fetched.
        pre_instances = (
            self.model._base_manager.using(self.db)
            .only(*(field.name for field in logging_config["logging_fields"]))
            .in_bulk([obj.pk for obj in objs])
        )

        res = super().bulk_update(objs, fields, **kwargs)

        for obj in objs:
            obj._fieldlogger_pre_instance = pre_instances.get(obj.pk)

        try:
            _log_fields(
                self.model, objs, update_fields=fields, run_callbacks=run_callbacks
            )
        finally:
            for obj in objs:
                del obj._fieldlogger_pre_instance

        return res
