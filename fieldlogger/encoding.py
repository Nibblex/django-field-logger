from datetime import date, datetime, time, timedelta
from decimal import Decimal
from json import JSONDecoder, JSONEncoder
from uuid import UUID

from django.conf import settings
from django.core.files import File
from django.db import models
from django.utils.module_loading import import_string

SETTINGS = getattr(settings, "FIELD_LOGGER_SETTINGS", {})


class Encoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (date, datetime, time)):
            return obj.isoformat()
        elif isinstance(obj, timedelta):
            return str(obj.total_seconds())
        elif isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, (bytes, bytearray)):
            return obj.decode()
        elif isinstance(obj, memoryview):
            return obj.tobytes().decode()
        elif isinstance(obj, File):
            return obj.name
        elif isinstance(obj, UUID):
            return str(obj)
        elif isinstance(obj, models.Model):
            return obj.pk
        elif isinstance(obj, models.QuerySet):
            return list(obj.values_list("pk", flat=True))

        return super().default(obj)


class Decoder(JSONDecoder):
    pass


ENCODER = SETTINGS.get("ENCODER")
ENCODER = import_string(ENCODER) if ENCODER else Encoder

DECODER = SETTINGS.get("DECODER")
DECODER = import_string(DECODER) if DECODER else Decoder
