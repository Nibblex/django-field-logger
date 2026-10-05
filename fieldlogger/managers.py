"""QuerySet and manager that add field logging to bulk operations."""

import functools
from typing import (
    Any,
    Callable,
    Collection,
    Dict,
    FrozenSet,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
    Type,
    TypeVar,
    cast,
)

import django
from asgiref.sync import sync_to_async
from django.db import models
from django.db.models import Q
from django.db.models.fields import Field

from .config import get_config
from .db import batches, db_supports_returning_pks, reset_sequences, set_primary_keys
from .fieldlogger import PRE_INSTANCE_ATTR
from .fieldlogger import log_fields as _log_fields

_M = TypeVar("_M", bound=models.Model)


def _unique_field(model: Type[models.Model], name: str) -> Field:
    """Resolve a ``unique_fields`` entry, which may be ``"pk"``."""
    # Django only accepts concrete fields there, never reverse relations.
    return model._meta.pk if name == "pk" else cast(Field, model._meta.get_field(name))


# SQLite rejects expressions nested deeper than 1000 levels (its default
# SQLITE_MAX_EXPR_DEPTH), and a chain of ORs nests one level per term.
MAX_OR_TERMS = 500


def _key(obj: models.Model, group: Tuple[Field, ...]) -> Tuple[Any, ...]:
    return tuple(getattr(obj, field.attname) for field in group)


def _match_condition(group: Tuple[Field, ...], keys: Collection[Tuple[Any, ...]]) -> Q:
    """Condition matching rows whose ``group`` values equal any of ``keys``:
    an ``IN`` list for a single field, an OR of ANDs otherwise."""
    if len(group) == 1:
        return Q(**{f"{group[0].attname}__in": [key[0] for key in keys]})

    condition = Q()
    for key in keys:
        condition |= Q(**{field.attname: value for field, value in zip(group, key)})
    return condition


def existing_rows(
    model: Type[_M],
    objs: Sequence[_M],
    unique_fields: Optional[Collection[str]],
    logging_fields: FrozenSet[Field],
    using: Optional[str],
) -> Dict[int, _M]:
    """Return the database rows that ``objs`` conflict with, keyed by the
    index of the object in ``objs``.

    These are the rows that ``bulk_create(update_conflicts=True)`` updates
    instead of inserting. A row conflicts when it has the same values for
    every field in ``unique_fields``; without them (MySQL, which upserts on
    any unique constraint) on any single unique field. Objects with a null
    value in the compared fields never conflict, like in the database.

    Rows are fetched with one query per batch of objects, sized to stay
    within the database's limits on query parameters and expression depth.
    """
    groups: List[Tuple[Field, ...]] = (
        [tuple(_unique_field(model, name) for name in unique_fields)]
        if unique_fields
        else [(field,) for field in model._meta.concrete_fields if field.unique]
    )
    fields = [field for group in groups for field in group]
    multi_field = any(len(group) > 1 for group in groups)

    only = {field.name for field in logging_fields} | {field.name for field in fields}
    found: Dict[Tuple[Field, ...], Dict[Tuple[Any, ...], _M]] = {
        group: {} for group in groups
    }
    for batch in batches(
        objs, fields, using, max_size=MAX_OR_TERMS if multi_field else None
    ):
        condition = Q()
        for group in groups:
            keys = {
                key for key in (_key(obj, group) for obj in batch) if None not in key
            }
            if keys:
                condition |= _match_condition(group, keys)
        if not condition:
            continue

        for row in model._base_manager.using(using).filter(condition).only(*only):
            for group in groups:
                found[group][_key(row, group)] = row

    rows: Dict[int, _M] = {}
    for index, obj in enumerate(objs):
        for group in groups:
            key = _key(obj, group)
            if None not in key and key in found[group]:
                rows[index] = found[group][key]
                break

    return rows


def log_upserted(
    model: Type[_M],
    upserted: Iterable[Tuple[_M, _M]],
    update_fields: Optional[Iterable[str]],
    run_callbacks: bool,
    using: Optional[str] = None,
) -> None:
    """Log objects that ``bulk_create(update_conflicts=True)`` used to
    update existing rows, given as ``(object, previous row)`` pairs.

    Only ``update_fields`` are written by the upsert, so only they are
    compared. The objects get the primary key of the updated row, which
    Django < 5.0 does not set.
    """
    upserted = list(upserted)
    for obj, row in upserted:
        obj.pk = row.pk
        setattr(obj, PRE_INSTANCE_ATTR, row)

    try:
        _log_fields(
            model,
            [obj for obj, _ in upserted],
            update_fields=update_fields,
            run_callbacks=run_callbacks,
            using=using,
        )
    finally:
        for obj, _ in upserted:
            delattr(obj, PRE_INSTANCE_ATTR)


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
        update_conflicts = kwargs.get("update_conflicts", False)
        logging_config = get_config().get(self.model)
        tracking = log_fields and logging_config is not None

        # With update_conflicts, objects matching an existing row update it
        # instead of being inserted; they are logged as changes, not as
        # creations.
        existing = (
            existing_rows(
                self.model,
                objs,
                kwargs.get("unique_fields"),
                logging_config["logging_fields"],
                self.db,
            )
            if update_conflicts and log_fields and logging_config is not None
            else {}
        )
        new_objs = [obj for index, obj in enumerate(objs) if index not in existing]

        # Primary keys must be assigned manually so the logs can reference
        # their instances when Django does not set them: with
        # ignore_conflicts, on databases that cannot return them from bulk
        # inserts, and with update_conflicts before Django 5.0. With
        # update_conflicts they are only assigned when logging, to the new
        # objects alone: an object that updates an existing row would keep
        # a primary key that is not its row's.
        unsaved = [obj for obj in new_objs if obj.pk is None]
        returning = db_supports_returning_pks(self.model, using=self.db)
        manual_pks = isinstance(self.model._meta.pk, models.AutoField) and (
            tracking and (django.VERSION < (5, 0) or not returning)
            if update_conflicts
            else ignore_conflicts or not returning
        )
        if manual_pks:
            set_primary_keys(new_objs, self.model, using=self.db)

        res = super().bulk_create(objs, **kwargs)

        if manual_pks:
            reset_sequences(self.model, using=self.db)

        inserted = new_objs
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
            log_upserted(
                self.model,
                ((objs[index], row) for index, row in existing.items()),
                kwargs.get("update_fields"),
                run_callbacks,
                using=self.db,
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
