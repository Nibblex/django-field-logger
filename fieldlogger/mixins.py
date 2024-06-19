from django.db import models

from .models import FieldLog


class FieldLoggerMixin(models.Model):
    @property
    def fieldlog_set(self):
        return FieldLog.objects.filter(
            instance_id=self.pk,
            model_name=self._meta.model_name,
            app_label=self._meta.app_label,
        )

    class Meta:
        abstract = True
