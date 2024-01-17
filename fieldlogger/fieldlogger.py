from django.core.exceptions import FieldDoesNotExist

from .models import FieldLog

# Helpers


def rgetattr(obj, attr, *args):
    from functools import reduce

    def _getattr(obj, attr):
        return getattr(obj, attr, *args)

    return reduce(_getattr, [obj] + attr.split("."))


def rsetattr(obj, attr, val, save=False):
    pre, _, post = attr.rpartition(".")
    obj_to_save = rgetattr(obj, pre) if pre else obj
    setattr(obj_to_save, post, val)
    if save:
        obj_to_save.save(update_fields=[post])


# Main function


def log_fields(instance, fields):
    logs = {}

    pre_instance = instance.__class__.objects.filter(pk=instance.pk).first()
    if not pre_instance:
        return logs

    for field in fields:
        try:
            field_model = instance._meta.get_field(field)
            new_value = field_model.to_python(rgetattr(instance, field))
            old_value = rgetattr(pre_instance, field)
        except (FieldDoesNotExist, AttributeError):
            continue

        if new_value == old_value:
            continue

        logs[field] = FieldLog.objects.create(
            app_label=instance._meta.app_label,
            model=instance._meta.model_name,
            instance_id=instance.pk,
            field=field,
            old_value=old_value,
            new_value=new_value,
        )

        rsetattr(instance, field, new_value)

    return logs
