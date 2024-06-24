from django.db.models.signals import post_save, pre_save

from .config import LOGGING_CONFIG
from .fieldlogger import log_fields


def pre_save_log_fields(sender, instance, *args, **kwargs):
    logging_config = LOGGING_CONFIG.get(sender, {})

    update_fields = kwargs["update_fields"] or frozenset()

    logging_fields = logging_config.get("logging_fields", frozenset())
    related_fields = logging_config.get("_related_fields", frozenset())
    if update_fields:
        logging_fields &= update_fields
        related_fields = frozenset(
            rfield for rfield in related_fields if rfield[2] in update_fields
        )

    instance._fieldlogger_logging_fields = (
        frozenset((None, "", f) for f in logging_fields) | related_fields
    )

    if instance.pk:
        instance._fieldlogger_pre_instance = sender.objects.get(pk=instance.pk)


def post_save_log_fields(sender, instance, created, *args, **kwargs):
    logging_fields = getattr(instance, "_fieldlogger_logging_fields", frozenset())
    pre_instance = getattr(instance, "_fieldlogger_pre_instance", None)

    # Log fields
    log_fields(instance, logging_fields, pre_instance)

    # Clean up
    if hasattr(instance, "_fieldlogger_logging_fields"):
        del instance._fieldlogger_logging_fields
    if hasattr(instance, "_fieldlogger_pre_instance"):
        del instance._fieldlogger_pre_instance


for model_class in LOGGING_CONFIG:
    pre_save.connect(pre_save_log_fields, model_class)
    post_save.connect(post_save_log_fields, model_class)
