from .models import FieldLog

from django.db import models


class FieldLoggerMixin(models.Model):
    @property
    def fieldlog_set(self):
        return FieldLog.objects.filter(
            instance_id=self.pk,
            model=self._meta.model_name,
            app_label=self._meta.app_label,
        )

    class Meta:
        abstract = True
