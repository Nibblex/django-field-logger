"""The callbacks run after logging: their signature and how they are run."""

import logging
from typing import Any, Callable, Dict, FrozenSet, Iterable

from django.db.models import Model
from django.db.models.fields import Field

from .models import FieldLog

logger = logging.getLogger(__name__)

# Logs created for one instance, keyed by field name.
InstanceLogs = Dict[str, FieldLog]

# Logs created in a single operation, keyed by instance pk and field name.
Logs = Dict[Any, InstanceLogs]

# Signature of the callback functions run after logging an instance:
# (instance, logging_fields, logs keyed by field name) -> None
Callback = Callable[[Model, FrozenSet[Field], InstanceLogs], None]


def invoke_callbacks(
    instances: Iterable[Model],
    callbacks: Iterable[Callback],
    logs: Logs,
    logging_fields: FrozenSet[Field],
    fail_silently: bool = False,
) -> None:
    """Invoke every callback for every instance with its created logs.

    With ``fail_silently``, a failing callback is logged and the remaining
    ones still run; otherwise its exception propagates.
    """
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
