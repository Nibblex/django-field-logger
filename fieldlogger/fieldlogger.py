import logging
from typing import Dict, FrozenSet, List, Optional, Tuple

from .config import LOGGING_CONFIG
from .models import FieldLog, LoggableModel


def _run_callbacks(
    logging_instances: List[LoggableModel], logs: Dict[LoggableModel, Dict[str, FieldLog]]
):
    logging.info(f"{logging_instances}, logs: {logs}")
    for logging_instance in logging_instances:
        logging_config = LOGGING_CONFIG.get(logging_instance.__class__, {})

        for callback in logging_config["callbacks"]:
            try:
                callback(logging_instance, logs[logging_instance])
            except Exception as e:
                if not logging_config["fail_silently"]:
                    raise e


def log_fields(
    instance: LoggableModel,
    fields: FrozenSet[Tuple[Optional[LoggableModel], str, str]],
    pre_instance: LoggableModel = None,
):
    logging_instances, logs = [], {}

    instance.refresh_from_db(fields=[f[2] for f in fields])

    for cls, fieldpath, field in fields:
        try:
            new_value = getattr(instance, field)
            old_value = getattr(pre_instance, field) if pre_instance else None
        except AttributeError:
            continue

        if new_value == old_value:
            continue

        logging_instances = (
            cls.objects.filter(**{f"{fieldpath}__pk": instance.pk}) if cls else [instance]
        )

        for logging_instance in logging_instances:
            log = FieldLog.objects.create(
                app_label=logging_instance._meta.app_label,
                model_name=logging_instance._meta.model_name,
                instance_id=logging_instance.pk,
                field=f"{fieldpath}__{field}" if fieldpath else field,
                old_value=old_value,
                new_value=new_value,
                related=cls is not None,
                created=pre_instance is None,
            )
            logs.setdefault(logging_instance, {})[log.field] = log

    _run_callbacks(logging_instances, logs)
