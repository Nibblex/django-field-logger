from django.db.models.signals import post_save, pre_save

from .config import LOGGING_CONFIG
from .fieldlogger import log_fields


def pre_save_log_fields(sender, instance, *args, **kwargs):
    if instance.pk:
        instance._fieldlogger_pre_instance = sender.objects.filter(pk=instance.pk).first()


def post_save_log_fields(sender, instance, created, *args, **kwargs):
    update_fields = kwargs["update_fields"] or frozenset()

    # Log fields
    log_fields(sender, [instance], update_fields)

    # Clean up
    if hasattr(instance, "_fieldlogger_pre_instance"):
        del instance._fieldlogger_pre_instance


for model_class in LOGGING_CONFIG:
    pre_save.connect(pre_save_log_fields, model_class)
    post_save.connect(post_save_log_fields, model_class)
