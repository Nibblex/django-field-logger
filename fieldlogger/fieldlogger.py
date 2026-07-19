"""Core logging logic: detect field changes and create ``FieldLog`` records."""

import logging
from typing import Any, Dict, FrozenSet, Iterable, Optional, Sequence, Set, Type

from django.db import connections, router, transaction
from django.db.models import Max, Model
from django.db.models.fields import DecimalField, Field

from .config import get_config
from .models import Callback, FieldLog

# Logs created in a single operation, keyed by instance pk and field name.
Logs = Dict[Any, Dict[str, FieldLog]]

logger = logging.getLogger(__name__)


def db_supports_returning_pks(
    model_class: Type[Model], using: Optional[str] = None
) -> bool:
    """Return whether the database that ``model_class`` writes to sets
    primary keys on bulk-created objects.

    Backends without this capability need primary keys to be assigned
    manually with ``set_primary_keys`` before calling ``bulk_create``.
    """
    using = using or router.db_for_write(model_class)
    return connections[using].features.can_return_rows_from_bulk_insert


def set_primary_keys(
    objs: Sequence[Model], model_class: Type[Model], using: Optional[str] = None
) -> None:
    """Assign sequential primary keys to ``objs`` before a bulk insert.

    Needed on databases that cannot return primary keys from bulk inserts
    (see ``db_supports_returning_pks``). Objects that already have a
    primary key are left untouched.

    Note that concurrent bulk inserts may compute the same starting key;
    callers that need concurrency must serialize these operations.
    """
    using = using or router.db_for_write(model_class)
    with transaction.atomic(using=using):
        next_pk = (
            model_class.objects.using(using).aggregate(max_pk=Max("pk"))["max_pk"] or 0
        )
        for obj in objs:
            if obj.pk is None:
                next_pk += 1
                obj.pk = next_pk


def _log_fields(instances: Iterable[Model], logging_fields: FrozenSet[Field]) -> Logs:
    """Create a ``FieldLog`` for every changed field of every instance.

    The previous state of each instance is read from its
    ``_fieldlogger_pre_instance`` attribute; instances without it are
    considered newly created.
    """
    logs: Logs = {}
    field_logs_to_create = []

    for instance in instances:
        pre_instance = getattr(instance, "_fieldlogger_pre_instance", None)

        for field in logging_fields:
            try:
                new_value = getattr(instance, field.name)
                if isinstance(field, DecimalField):
                    new_value = FieldLog.from_db_field(field, new_value)

                old_value = getattr(pre_instance, field.name) if pre_instance else None

            except AttributeError:
                # E.g. a foreign key whose related instance was deleted.
                continue

            if new_value == old_value:
                continue

            field_log = FieldLog(
                app_label=instance._meta.app_label,
                model_name=instance._meta.model_name,
                instance_id=instance.pk,
                field=field.name,
                old_value=old_value,
                new_value=new_value,
                created=pre_instance is None,
            )

            field_logs_to_create.append(field_log)
            logs.setdefault(instance.pk, {})[field.name] = field_log

    if field_logs_to_create:
        if not db_supports_returning_pks(FieldLog):
            set_primary_keys(field_logs_to_create, FieldLog)
        FieldLog.objects.bulk_create(field_logs_to_create)

    return logs


def _run_callbacks(
    instances: Iterable[Model],
    callbacks: Iterable[Callback],
    logs: Logs,
    logging_fields: FrozenSet[Field],
    fail_silently: bool = False,
) -> None:
    """Invoke every callback for every instance with its created logs."""
    for instance in instances:
        instance_logs = logs.get(instance.pk, {})
        for callback in callbacks:
            try:
                callback(instance, logging_fields, instance_logs)
            except Exception:
                if not fail_silently:
                    raise
                logger.exception(
                    "Field logger callback %r failed for %r", callback, instance
                )


def log_fields(
    sender: Type[Model],
    instances: Iterable[Model],
    update_fields: Optional[Iterable[str]] = None,
    run_callbacks: bool = True,
) -> Logs:
    """Log field changes for ``instances`` of the ``sender`` model.

    If ``update_fields`` is given, only those fields are considered.
    Returns the created logs keyed by instance pk and field name; returns
    an empty dict if ``sender`` is not configured for logging.
    """
    logging_config = get_config().get(sender)
    if not logging_config:
        return {}

    logging_fields = logging_config["logging_fields"]
    if update_fields:
        update_fields = set(update_fields)
        logging_fields = frozenset(
            field for field in logging_fields if field.name in update_fields
        )

    logs = _log_fields(instances, logging_fields)

    if run_callbacks:
        _run_callbacks(
            instances,
            logging_config["callbacks"],
            logs,
            logging_fields,
            logging_config["fail_silently"],
        )

    return logs


def m2m_pks(
    field: Field, instance_pks: Iterable[Any], using: Optional[str] = None
) -> Dict[Any, Set[Any]]:
    """Return the pks currently related through ``field`` for each pk in
    ``instance_pks``, read from the through table."""
    through = field.remote_field.through
    source = field.m2m_field_name()
    target = field.m2m_reverse_field_name()

    state: Dict[Any, Set[Any]] = {pk: set() for pk in instance_pks}
    rows = (
        through._base_manager.using(using)
        .filter(**{f"{source}__in": list(state)})
        .values_list(source, target)
    )
    for source_pk, target_pk in rows:
        state[source_pk].add(target_pk)

    return state


def log_m2m_fields(
    model_class: Type[Model],
    field: Field,
    old_state: Dict[Any, Set[Any]],
    using: Optional[str] = None,
    run_callbacks: bool = True,
) -> Logs:
    """Log changes to the many-to-many ``field`` of ``model_class``.

    ``old_state`` maps instance pks to the sets of related pks before the
    change; instances whose current related pks differ get a log holding
    the old and new pk lists. Returns the created logs like ``log_fields``.
    """
    logging_config = get_config().get(model_class)
    if not logging_config or field not in logging_config["logging_m2m_fields"]:
        return {}

    new_state = m2m_pks(field, old_state, using)

    logs: Logs = {}
    field_logs_to_create = []
    for instance_pk, old_pks in old_state.items():
        new_pks = new_state[instance_pk]
        if old_pks == new_pks:
            continue

        field_log = FieldLog(
            app_label=model_class._meta.app_label,
            model_name=model_class._meta.model_name,
            instance_id=instance_pk,
            field=field.name,
            old_value=sorted(old_pks),
            new_value=sorted(new_pks),
        )
        field_logs_to_create.append(field_log)
        logs.setdefault(instance_pk, {})[field.name] = field_log

    if not field_logs_to_create:
        return logs

    if not db_supports_returning_pks(FieldLog):
        set_primary_keys(field_logs_to_create, FieldLog)
    FieldLog.objects.bulk_create(field_logs_to_create)

    if run_callbacks:
        instances = model_class._base_manager.using(using).filter(pk__in=list(logs))
        _run_callbacks(
            instances,
            logging_config["callbacks"],
            logs,
            frozenset({field}),
            logging_config["fail_silently"],
        )

    return logs
