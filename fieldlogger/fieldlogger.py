from typing import Dict, FrozenSet, Iterable

from django.core.exceptions import FieldDoesNotExist

from .models import Callback, FieldLog, LoggableModel


def _log_fields(
    instances: Iterable[LoggableModel],
    logging_fields: FrozenSet[str] = None,
) -> Dict[str, FieldLog]:
    logs = {}
    field_logs_to_create = []

    for instance in instances:
        instance.refresh_from_db(fields=logging_fields)
        pre_instance = getattr(instance, "_fieldlogger_pre_instance", None)

        for field in logging_fields:
            try:
                new_value = getattr(instance, field)
                old_value = getattr(pre_instance, field) if pre_instance else None
            except (FieldDoesNotExist, AttributeError):
                continue

            if new_value == old_value:
                continue

            field_log = FieldLog(
                app_label=instance._meta.app_label,
                model_name=instance._meta.model_name,
                instance_id=instance.pk,
                field=field,
                old_value=old_value,
                new_value=new_value,
                created=pre_instance is None,
            )

            field_logs_to_create.append(field_log)
            logs.setdefault(instance.pk, {})[field] = field_log

    if field_logs_to_create:
        FieldLog.objects.bulk_create(field_logs_to_create)

    return logs


def _run_callbacks(
    instances: Iterable[LoggableModel],
    callbacks: Iterable[Callback],
    logs: Iterable[Dict[str, FieldLog]],
    logging_fields: FrozenSet[str] = None,
    fail_silently: bool = False,
):
    for instance in instances:
        for callback in callbacks:
            try:
                callback(instance, logging_fields, logs.get(instance.pk, {}))
            except Exception as e:
                if not fail_silently:
                    raise e


def log_fields(
    sender: LoggableModel,
    instances: Iterable[LoggableModel],
    update_fields: FrozenSet[str] = None,
    run_callbacks: bool = True,
) -> Dict[str, FieldLog]:
    from .config import LOGGING_CONFIG

    if sender not in LOGGING_CONFIG:
        return {}

    logging_config = LOGGING_CONFIG[sender]
    logging_fields = logging_config.get("logging_fields", frozenset())
    if update_fields:
        logging_fields = logging_fields & update_fields

    callbacks = logging_config.get("callbacks", [])
    fail_silently = logging_config.get("fail_silently", False)

    logs = _log_fields(instances, logging_fields)

    if run_callbacks:
        _run_callbacks(instances, callbacks, logs, logging_fields, fail_silently)

    return logs
