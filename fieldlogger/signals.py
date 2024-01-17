from django.db.models.signals import pre_save, post_save

from .config import LOGGING_CONFIG, logging_fields
from .fieldlogger import log_fields


def pre_save_log_fields(sender, instance, *args, **kwargs):
    using_fields = logging_fields(instance)

    update_fields = kwargs["update_fields"] or frozenset()
    if update_fields:
        using_fields = using_fields & update_fields

    instance._fieldlogger_using_fields = using_fields

    if instance.pk:
        instance._fieldlogger_pre_instance = sender.objects.get(pk=instance.pk)


def post_save_log_fields(sender, instance, created, *args, **kwargs):
    using_fields = getattr(instance, "_fieldlogger_using_fields", None)
    pre_instance = getattr(instance, "_fieldlogger_pre_instance", None)

    if using_fields is not None:
        logs = log_fields(instance, using_fields, pre_instance)

        callbacks = LOGGING_CONFIG[sender._meta.label].get("callbacks", [])
        for callback in callbacks:
            callback(instance, using_fields, logs)

        del instance._fieldlogger_using_fields

    if pre_instance is not None:
        del instance._fieldlogger_pre_instance


for label in LOGGING_CONFIG:
    pre_save.connect(pre_save_log_fields, label)
    post_save.connect(post_save_log_fields, label)
