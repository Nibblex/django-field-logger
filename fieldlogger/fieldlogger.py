from typing import Dict, FrozenSet

from django.core.exceptions import FieldDoesNotExist

from .models import Callback, FieldLog, LoggableModel
from .utils import rgetattr


def log_fields(
    instance: LoggableModel, fields: FrozenSet[str], pre_instance: LoggableModel = None
) -> Dict[str, FieldLog]:
    logs = {}

    instance.refresh_from_db(fields=fields)

    for field in fields:
        try:
            new_value = rgetattr(instance, field)
            old_value = rgetattr(pre_instance, field) if pre_instance else None
        except (FieldDoesNotExist, AttributeError):
            continue

        if new_value == old_value:
            continue

        logs[field] = FieldLog.objects.create(
            app_label=instance._meta.app_label,
            model_name=instance._meta.model_name,
            instance_id=instance.pk,
            field=field,
            old_value=old_value,
            new_value=new_value,
            created=pre_instance is None,
        )

    return logs


def run_callbacks(
    instance: LoggableModel,
    callbacks: FrozenSet[Callback],
    fields: FrozenSet[str],
    logs: Dict[str, FieldLog],
    fail_silently: bool = False,
):
    for callback in callbacks:
        try:
            callback(instance, fields, logs)
        except Exception as e:
            if fail_silently:
                continue
            raise e
