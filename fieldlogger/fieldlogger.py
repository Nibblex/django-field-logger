from django.core.exceptions import FieldDoesNotExist

from .models import FieldLog
from .utils import rgetattr, rsetattr


def log_fields(instance, fields, pre_instance=None):
    logs = {}

    for field in fields:
        try:
            field_model = instance._meta.get_field(field)
            new_value = field_model.to_python(rgetattr(instance, field))
            old_value = rgetattr(pre_instance, field) if pre_instance else None
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
            created=pre_instance is None,
        )

        rsetattr(instance, field, new_value)

    return logs
