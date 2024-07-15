from typing import Callable, Dict, FrozenSet, NewType

from django.apps import apps
from django.db import models
from django.utils.translation import gettext_lazy as _

from .encoding import DECODER, ENCODER
from .utils import getrmodel


class FieldLog(models.Model):
    app_label = models.CharField(max_length=100, editable=False)
    model_name = models.CharField(max_length=100, editable=False)
    instance_id = models.CharField(max_length=255, editable=False)
    field = models.CharField(_("field name"), max_length=100, editable=False)
    timestamp = models.DateTimeField(auto_now=True, editable=False)
    old_value = models.JSONField(
        encoder=ENCODER, decoder=DECODER, blank=True, null=True, editable=False
    )
    new_value = models.JSONField(
        encoder=ENCODER, decoder=DECODER, blank=True, null=True, editable=False
    )
    extra_data = models.JSONField(encoder=ENCODER, decoder=DECODER, default=dict)
    created = models.BooleanField(default=False, editable=False)

    def __str__(self):
        return f"({self.app_label}__{self.model_name}__{self.field}, created={self.created})\
        {self.old_value} -> {self.new_value}"

    @staticmethod
    def from_db_field(field_class, value):
        if field_class.__class__ is models.BinaryField:
            value = bytes(value, "utf-8") if isinstance(value, str) else value
        elif field_class.__class__ is models.DecimalField:
            value = round(value, field_class.decimal_places) if value else value
        elif field_class.__class__ is models.ForeignKey:
            return field_class.related_model.objects.get(pk=value) if value else None

        return field_class.to_python(value)

    @classmethod
    def from_db(cls, db, field_names, values):
        model_class = apps.get_model(values[1], values[2])
        fieldpath, _, field = values[4].rpartition("__")
        model_class = getrmodel(model_class, fieldpath) or model_class
        field_class = model_class._meta.get_field(field)

        values[3] = model_class._meta.pk.to_python(values[3])
        values[6] = cls.from_db_field(field_class, values[6]) if not values[9] else None
        values[7] = cls.from_db_field(field_class, values[7])

        return super().from_db(db, field_names, values)

    @property
    def model(self):
        return apps.get_model(self.app_label, self.model_name)

    @property
    def instance(self):
        return self.model.objects.get(pk=self.instance_id)

    @property
    def previous_log(self):
        return (
            self.__class__.objects.filter(
                app_label=self.app_label,
                model_name=self.model_name,
                instance_id=self.instance_id,
                field=self.field,
            )
            .exclude(pk=self.pk)
            .order_by("pk")
            .last()
        )


LoggableModel = NewType("LoggableModel", models.Model)
Callback = Callable[[LoggableModel, FrozenSet[str], Dict[str, FieldLog]], None]
