from django.db.models.signals import post_save, pre_save

from .config import LOGGING_CONFIG
from .fieldlogger import log_fields, run_callbacks


def pre_save_log_fields(sender, instance, *args, **kwargs):
    using_fields = LOGGING_CONFIG.get(sender, {}).get("logging_fields", frozenset())

    update_fields = kwargs["update_fields"] or frozenset()
    if update_fields:
        using_fields = using_fields & update_fields

    instance._fieldlogger_using_fields = using_fields

    if instance.pk:
        instance._fieldlogger_pre_instance = sender.objects.filter(pk=instance.pk).first()


def post_save_log_fields(sender, instance, created, *args, **kwargs):
    using_fields = getattr(instance, "_fieldlogger_using_fields", None)
    pre_instance = getattr(instance, "_fieldlogger_pre_instance", None)

    if using_fields and (pre_instance or created):
        # Get logs
        logs = log_fields(instance, using_fields, pre_instance)

        # Run callbacks
        callbacks = LOGGING_CONFIG[sender]["callbacks"]
        fail_silently = LOGGING_CONFIG[sender]["fail_silently"]
        run_callbacks(instance, callbacks, using_fields, logs, fail_silently)

    # Clean up
    if hasattr(instance, "_fieldlogger_using_fields"):
        del instance._fieldlogger_using_fields
    if hasattr(instance, "_fieldlogger_pre_instance"):
        del instance._fieldlogger_pre_instance


for model_class in LOGGING_CONFIG:
    pre_save.connect(pre_save_log_fields, model_class)
    post_save.connect(post_save_log_fields, model_class)
