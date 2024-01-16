from django.db.models.signals import pre_save

from .config import LOGGING_CONFIG, logging_fields
from .fieldlogger import log_fields


def log_dirty_fields(sender, instance, *args, **kwargs):
    if instance.pk:
        using_fields = logging_fields(instance)

        update_fields = kwargs["update_fields"] or frozenset()
        if update_fields:
            using_fields = using_fields & update_fields

        if using_fields:
            logs = log_fields(instance, using_fields)
            if logs and "timestamps" not in update_fields:
                kwargs["update_fields"] = update_fields | frozenset(["timestamps"])

            callbacks = LOGGING_CONFIG[sender._meta.label].get("callbacks", [])
            for callback in callbacks:
                callback(instance, using_fields, logs)


for label in LOGGING_CONFIG:
    pre_save.connect(log_dirty_fields, label)
