"""Core logging logic: detect field changes and create ``FieldLog`` records."""

from typing import Any, Dict, FrozenSet, Iterable, Optional, Sequence, Set, Type, cast

from django.db import connections, router, transaction
from django.db.models import ManyToManyField, Model
from django.db.models.fields import Field
from django.db.models.fields.files import FieldFile

from .callbacks import Logs, invoke_callbacks
from .config import get_config, through_model
from .db import batches, db_supports_returning_pks
from .models import FieldLog

# Attributes where the pre-change state of an instance is stashed between
# the "pre" and "post" signals (or around a bulk update).
PRE_INSTANCE_ATTR = "_fieldlogger_pre_instance"
PRE_M2M_ATTR = "_fieldlogger_pre_m2m"


def _save_logs(field_logs: Sequence[FieldLog]) -> None:
    """Insert ``field_logs``, setting their primary keys.

    Callbacks receive the logs and may save them or follow
    ``previous_log``, so they need their keys. Where ``bulk_create`` does
    not set them, each log is inserted on its own so the database assigns
    it, without guessing keys or bypassing the table's sequence.
    """
    using = router.db_for_write(FieldLog)
    if db_supports_returning_pks(FieldLog, using):
        FieldLog.objects.using(using).bulk_create(field_logs)
        return

    with transaction.atomic(using=using):
        for field_log in field_logs:
            field_log.save(using=using, force_insert=True)


def _stored_value(row: Model, field: Field, empty_is_null: bool) -> Any:
    """Value of ``field`` in a row read from the database.

    ``empty_is_null`` is set on databases that store empty strings as NULL
    (Oracle), where Django reads NULL text and binary columns back as empty
    values; they are logged as None, so that creating a row does not log a
    change from None to an empty value.
    """
    value = getattr(row, field.attname)
    if isinstance(value, FieldFile):
        # Files are logged by name; Django stores "no file" as an empty
        # name, which is logged as None like any other missing value.
        return value.name or None
    if empty_is_null and value in ("", b""):
        return None
    return value


def _log_fields(
    model_class: Type[Model],
    instances: Sequence[Model],
    logging_fields: FrozenSet[Field],
    using: Optional[str] = None,
) -> Logs:
    """Create a ``FieldLog`` for every changed field of every instance.

    The previous state of each instance is read from its
    ``PRE_INSTANCE_ATTR`` attribute; instances without it are considered
    newly created. The new state is read back from the database rather
    than from the instances: in memory a field may hold an expression
    (``F()``, a database function, ``db_default``) or a value the database
    stores differently (e.g. a ``Decimal`` with more decimal places than
    the field). Instances whose row is not found are not logged.

    Values are compared by ``attname``, so foreign keys are compared by
    their raw value without fetching the related instances.
    """
    if not logging_fields or not instances:
        return {}

    using = using or router.db_for_write(model_class)
    empty_is_null = connections[using].features.interprets_empty_strings_as_nulls
    stored = (
        model_class._base_manager.using(using)
        .only(*(field.name for field in logging_fields))
        .in_bulk([instance.pk for instance in instances])
    )

    logs: Logs = {}
    field_logs_to_create = []

    for instance in instances:
        row = stored.get(instance.pk)
        if row is None:
            continue

        pre_instance = getattr(instance, PRE_INSTANCE_ATTR, None)

        for field in logging_fields:
            new_value = _stored_value(row, field, empty_is_null)
            old_value = (
                _stored_value(pre_instance, field, empty_is_null)
                if pre_instance
                else None
            )
            if new_value == old_value:
                continue

            field_log = FieldLog(
                app_label=instance._meta.app_label,
                # Always set on concrete models; Optional only in the stubs.
                model_name=cast(str, instance._meta.model_name),
                instance_id=instance.pk,
                field=field.name,
                old_value=old_value,
                new_value=new_value,
                created=pre_instance is None,
            )

            field_logs_to_create.append(field_log)
            logs.setdefault(instance.pk, {})[field.name] = field_log

    if field_logs_to_create:
        _save_logs(field_logs_to_create)

        # Give callbacks the same values as a log loaded from the database
        # (e.g. related instances instead of raw foreign key values).
        for field_log in field_logs_to_create:
            field_log._convert_db_values()

    return logs


def log_fields(
    sender: Type[Model],
    instances: Iterable[Model],
    update_fields: Optional[Iterable[str]] = None,
    run_callbacks: bool = True,
    using: Optional[str] = None,
) -> Logs:
    """Log field changes for ``instances`` of the ``sender`` model.

    If ``update_fields`` is given, only those fields are considered. The
    new values are read from the ``using`` database (by default, the one
    the model is written to).
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

    instances = list(instances)
    logs = _log_fields(sender, instances, logging_fields, using)

    if run_callbacks:
        invoke_callbacks(
            instances,
            logging_config["callbacks"],
            logs,
            logging_fields,
            logging_config["fail_silently"],
        )

    return logs


def m2m_pks(
    field: ManyToManyField, instance_pks: Iterable[Any], using: Optional[str] = None
) -> Dict[Any, Set[Any]]:
    """Return the pks currently related through ``field`` for each pk in
    ``instance_pks``, read from the through table."""
    through = through_model(field)
    source = field.m2m_field_name()
    target = field.m2m_reverse_field_name()

    state: Dict[Any, Set[Any]] = {pk: set() for pk in instance_pks}
    # A foreign key of the through model, never a reverse relation.
    source_field = cast(Field, through._meta.get_field(source))
    for batch in batches(list(state), [source_field], using):
        rows = (
            through._base_manager.using(using)
            .filter(**{f"{source}__in": batch})
            .values_list(source, target)
        )
        for source_pk, target_pk in rows:
            state[source_pk].add(target_pk)

    return state


def log_m2m_fields(
    model_class: Type[Model],
    field: ManyToManyField,
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
            model_name=cast(str, model_class._meta.model_name),
            instance_id=instance_pk,
            field=field.name,
            old_value=sorted(old_pks),
            new_value=sorted(new_pks),
        )
        field_logs_to_create.append(field_log)
        logs.setdefault(instance_pk, {})[field.name] = field_log

    if not field_logs_to_create:
        return logs

    _save_logs(field_logs_to_create)

    if run_callbacks:
        pk_field = model_class._meta.pk
        instances = [
            instance
            for batch in batches(list(logs), [pk_field], using)
            for instance in model_class._base_manager.using(using).filter(pk__in=batch)
        ]
        invoke_callbacks(
            instances,
            logging_config["callbacks"],
            logs,
            frozenset({field}),
            logging_config["fail_silently"],
        )

    return logs
