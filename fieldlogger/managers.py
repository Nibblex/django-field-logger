"""Manager that adds field logging to bulk operations."""

from typing import Any, Iterable, List, Optional, Sequence, TypeVar

from django.db import models

from .config import get_config
from .db import batches, db_supports_returning_pks, reset_sequences, set_primary_keys
from .fieldlogger import PRE_INSTANCE_ATTR
from .fieldlogger import log_fields as _log_fields

_M = TypeVar("_M", bound=models.Model)


class FieldLoggerManager(models.Manager[_M]):
    """Logs field changes on ``bulk_create`` and ``bulk_update``.

    Both methods accept two extra keyword arguments: ``log_fields`` to
    disable logging for the call, and ``run_callbacks`` to skip the
    configured callbacks.
    """

    def bulk_create(  # type: ignore[override]
        self,
        objs: Iterable[_M],
        log_fields: bool = True,
        run_callbacks: bool = True,
        **kwargs: Any,
    ) -> List[_M]:
        # Materialized because the objects are iterated more than once.
        objs = list(objs)

        ignore_conflicts = kwargs.get("ignore_conflicts", False)

        # With ignore_conflicts, or on databases that cannot return primary
        # keys from bulk inserts, pks are assigned manually so the logs can
        # reference their instances.
        unsaved = [obj for obj in objs if obj.pk is None]
        manual_pks = isinstance(self.model._meta.pk, models.AutoField) and (
            ignore_conflicts or not db_supports_returning_pks(self.model, using=self.db)
        )
        if manual_pks:
            set_primary_keys(objs, self.model, using=self.db)

        res = super().bulk_create(objs, **kwargs)

        if manual_pks:
            reset_sequences(self.model, using=self.db)

        inserted = objs
        if ignore_conflicts and (log_fields or manual_pks):
            # Rows that conflicted were not inserted: they are not logged,
            # and the keys assigned to them are cleared, since no row has
            # them (saving such an object would insert with that key).
            pks = [obj.pk for obj in objs]
            inserted_pks = {
                pk
                for batch in batches(pks, [self.model._meta.pk], self.db)
                for pk in self.model._base_manager.using(self.db)
                .filter(pk__in=batch)
                .values_list("pk", flat=True)
            }
            inserted = [obj for obj in objs if obj.pk in inserted_pks]
            if manual_pks:
                for obj in unsaved:
                    if obj.pk not in inserted_pks:
                        obj.pk = None

        if log_fields:
            _log_fields(
                self.model, inserted, run_callbacks=run_callbacks, using=self.db
            )

        return res

    def bulk_update(  # type: ignore[override]
        self,
        objs: Iterable[_M],
        fields: Sequence[str],
        log_fields: bool = True,
        run_callbacks: bool = True,
        **kwargs: Any,
    ) -> Optional[int]:
        # Returns the number of updated rows; None on Django < 4.0.

        # Materialized because the objects are iterated more than once.
        objs = list(objs)

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
            setattr(obj, PRE_INSTANCE_ATTR, pre_instances.get(obj.pk))

        try:
            _log_fields(
                self.model,
                objs,
                update_fields=fields,
                run_callbacks=run_callbacks,
                using=self.db,
            )
        finally:
            for obj in objs:
                delattr(obj, PRE_INSTANCE_ATTR)

        return res
