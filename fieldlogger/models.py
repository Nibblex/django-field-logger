"""The ``FieldLog`` model and the ``Callback`` type alias."""

from base64 import b64decode
from functools import cached_property
from typing import Any, Callable, Dict, FrozenSet, Optional, Type

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.utils.functional import SimpleLazyObject
from django.utils.translation import gettext_lazy as _

from .encoding import DECODER, ENCODER
from .utils import getrmodel

# Fields needed by ``FieldLog.from_db`` to convert raw values; if any of
# them is deferred, the conversion is skipped.
_CONVERSION_FIELDS = frozenset(
    [
        "app_label",
        "model_name",
        "instance_id",
        "field",
        "old_value",
        "new_value",
        "created",
    ]
)


def _fetch_related(field: models.ForeignKey, pk: Any) -> models.Model:
    """Fetch the related instance of a logged foreign key value.

    If the instance no longer exists, return an unsaved shell instance
    carrying only the primary key, so reading old logs never fails.
    """
    try:
        return field.related_model._base_manager.get(pk=pk)
    except field.related_model.DoesNotExist:
        return field.related_model(pk=pk)


class FieldLog(models.Model):
    """A single change to a field of a logged model instance."""

    app_label = models.CharField(max_length=100, editable=False)
    model_name = models.CharField(max_length=100, editable=False)
    instance_id = models.CharField(max_length=255, editable=False)
    field = models.CharField(_("field name"), max_length=100, editable=False)
    timestamp = models.DateTimeField(auto_now_add=True, editable=False)
    old_value = models.JSONField(
        encoder=ENCODER, decoder=DECODER, blank=True, null=True, editable=False
    )
    new_value = models.JSONField(
        encoder=ENCODER, decoder=DECODER, blank=True, null=True, editable=False
    )
    extra_data = models.JSONField(encoder=ENCODER, decoder=DECODER, default=dict)
    created = models.BooleanField(default=False, editable=False)

    class Meta:
        indexes = [
            models.Index(
                fields=["app_label", "model_name", "instance_id", "field"],
                name="fieldlogger_instance_idx",
            ),
        ]

    def __str__(self):
        return (
            f"({self.app_label}__{self.model_name}__{self.field}, "
            f"created={self.created}) {self.old_value} -> {self.new_value}"
        )

    @staticmethod
    def from_db_field(field: models.Field, value: Any) -> Any:
        """Convert a JSON-decoded ``value`` back to the Python object that
        ``field`` would hold on its model instance."""
        if isinstance(field, models.BinaryField):
            if isinstance(value, str):
                try:
                    value = b64decode(value)
                except ValueError:
                    # Logs written before binary values were base64-encoded.
                    value = bytes(value, "utf-8")
        elif isinstance(field, models.DecimalField):
            if value is not None:
                value = round(field.to_python(value), field.decimal_places)
        elif isinstance(field, models.ForeignKey):
            if not value:
                return None
            # Lazy so that loading logs does not query one related
            # instance per row.
            return SimpleLazyObject(lambda: _fetch_related(field, value))

        return field.to_python(value)

    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        if _CONVERSION_FIELDS.issubset(field_names):
            instance._convert_db_values()
        return instance

    def _convert_db_values(self) -> None:
        """Convert the JSON-decoded values to the Python objects of the
        logged field.

        ``old_value``/``new_value`` are stored as JSON, so on load they are
        converted back using the original model field (e.g. strings become
        ``Decimal`` or related instances). Logs whose model or field no
        longer exists are left as decoded JSON.
        """
        if self.created:
            # Newly created instances have no previous value.
            self.old_value = None

        try:
            model_class = apps.get_model(self.app_label, self.model_name)
        except LookupError:
            return

        field_path, _, field_name = self.field.rpartition("__")
        model_class = getrmodel(model_class, field_path) or model_class

        self.instance_id = model_class._meta.pk.to_python(self.instance_id)

        try:
            field = model_class._meta.get_field(field_name)
        except FieldDoesNotExist:
            return

        if not self.created:
            self.old_value = self.from_db_field(field, self.old_value)

        self.new_value = self.from_db_field(field, self.new_value)

    @cached_property
    def model(self) -> Type[models.Model]:
        """The model class of the logged instance."""
        return apps.get_model(self.app_label, self.model_name)

    @cached_property
    def instance(self) -> models.Model:
        """The logged instance, fetched from the database."""
        return self.model._base_manager.get(pk=self.instance_id)

    @cached_property
    def previous_log(self) -> Optional["FieldLog"]:
        """The previous log of the same field of the same instance, if any."""
        return (
            self.__class__.objects.filter(
                app_label=self.app_label,
                model_name=self.model_name,
                instance_id=self.instance_id,
                field=self.field,
                pk__lt=self.pk,
            )
            .order_by("-pk")
            .first()
        )


# Signature of the callback functions run after logging an instance:
# (instance, logging_fields, logs keyed by field name) -> None
Callback = Callable[[models.Model, FrozenSet[models.Field], Dict[str, FieldLog]], None]
