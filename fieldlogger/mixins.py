"""Mixin that gives logged models easy access to their logs."""

from django.db import models

from .models import FieldLog


class FieldLoggerMixin(models.Model):
    """Adds a ``fieldlog_set`` property to a logged model.

    ``FieldLog`` has no foreign key to the logged models, so this property
    provides the equivalent of a reverse relation.
    """

    @property
    def fieldlog_set(self) -> "models.QuerySet[FieldLog]":
        """Queryset with all the logs of this instance.

        A new one on every access, like Django's reverse relations: a
        cached one would keep the results of its first evaluation and the
        primary key of its first access.
        """
        return FieldLog.objects.filter(
            instance_id=self.pk,
            model_name=self._meta.model_name,
            app_label=self._meta.app_label,
        )

    class Meta:
        abstract = True
