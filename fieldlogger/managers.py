"""QuerySet and manager that add field logging to bulk operations."""

import functools
from typing import Any, Callable, Iterable, List, Optional, Sequence, Type, TypeVar

from asgiref.sync import sync_to_async
from django.db import models

from .config import get_config
from .db import batches, db_supports_returning_pks, reset_sequences, set_primary_keys
from .fieldlogger import PRE_INSTANCE_ATTR
from .fieldlogger import log_fields as _log_fields

_M = TypeVar("_M", bound=models.Model)


class FieldLoggerQuerySet(models.QuerySet[_M]):
    """Logs field changes on ``bulk_create`` and ``bulk_update``, and on
    their async variants.

    All of them accept two extra keyword arguments: ``log_fields`` to
    disable logging for the call, and ``run_callbacks`` to skip the
    configured callbacks. Being a QuerySet, logging also applies after
    ``using()``, ``filter()`` and other chained calls.
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
        # Resolve self.db to the write database, as Django does.
        self._for_write = True

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
        # Resolve self.db to the write database, as Django does.
        self._for_write = True

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

    # Django's async variants (4.1+) already call bulk_create/bulk_update,
    # so they are logged; these overrides only add the extra arguments,
    # which Django's signatures do not accept.

    async def abulk_create(  # type: ignore[override]
        self,
        objs: Iterable[_M],
        log_fields: bool = True,
        run_callbacks: bool = True,
        **kwargs: Any,
    ) -> List[_M]:
        return await sync_to_async(self.bulk_create)(
            objs, log_fields=log_fields, run_callbacks=run_callbacks, **kwargs
        )

    async def abulk_update(  # type: ignore[override]
        self,
        objs: Iterable[_M],
        fields: Sequence[str],
        log_fields: bool = True,
        run_callbacks: bool = True,
        **kwargs: Any,
    ) -> Optional[int]:
        return await sync_to_async(self.bulk_update)(
            objs,
            fields,
            log_fields=log_fields,
            run_callbacks=run_callbacks,
            **kwargs,
        )


def _with_logging(queryset_class: Type[models.QuerySet]) -> Type[models.QuerySet]:
    """``queryset_class`` combined with ``FieldLoggerQuerySet``, unless it
    already is one."""
    if issubclass(queryset_class, FieldLoggerQuerySet):
        return queryset_class
    return type(
        queryset_class.__name__,
        (FieldLoggerQuerySet, queryset_class),
        {"__module__": queryset_class.__module__},
    )


class FieldLoggerManager(models.Manager[_M]):
    """Manager whose querysets are ``FieldLoggerQuerySet``s, so bulk
    operations are logged whether called on the manager or on a queryset
    (e.g. ``Model.objects.using("other").bulk_create(...)``).

    Custom querysets are combined with ``FieldLoggerQuerySet``, both with
    ``FieldLoggerManager.from_queryset(MyQuerySet)`` and when a subclass
    overrides ``get_queryset()``.
    """

    _queryset_class = FieldLoggerQuerySet

    @classmethod
    def from_queryset(
        cls, queryset_class: Type[models.QuerySet], class_name: Optional[str] = None
    ) -> Any:
        return super().from_queryset(_with_logging(queryset_class), class_name)

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # A subclass overriding get_queryset() may return another QuerySet;
        # wrap it so its result always has the logging methods.
        get_queryset = cls.__dict__.get("get_queryset")
        if get_queryset is not None and not getattr(
            get_queryset, "_fieldlogger_wrapped", False
        ):
            cls.get_queryset = _logging_get_queryset(get_queryset)  # type: ignore[method-assign]


def _logging_get_queryset(get_queryset: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a manager's ``get_queryset`` so the QuerySet it returns has the
    logging methods of ``FieldLoggerQuerySet``."""

    @functools.wraps(get_queryset)
    def wrapper(self: models.Manager, *args: Any, **kwargs: Any) -> Any:
        queryset = get_queryset(self, *args, **kwargs)
        if not isinstance(queryset, FieldLoggerQuerySet):
            # A copy, so the class change does not leak to a shared
            # instance; the copy keeps its state (filters, database).
            queryset = queryset.all()
            queryset.__class__ = _with_logging(type(queryset))
        return queryset

    wrapper._fieldlogger_wrapped = True  # type: ignore[attr-defined]
    return wrapper
