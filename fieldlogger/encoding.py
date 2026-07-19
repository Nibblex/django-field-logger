"""JSON encoding/decoding of logged field values.

Custom classes can be configured through the ``ENCODER`` and ``DECODER``
keys of ``FIELD_LOGGER_SETTINGS`` as dotted import paths. They are part
of the ``FieldLog`` model definition, so they are resolved at import time
and changing them requires a restart.
"""

from base64 import b64encode
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from json import JSONDecoder, JSONEncoder
from uuid import UUID

from django.core.files import File
from django.db import models
from django.utils.module_loading import import_string

from .config import get_settings


class Encoder(JSONEncoder):
    """JSON encoder for the value types of the standard Django fields."""

    def default(self, obj):
        if isinstance(obj, (date, datetime, time)):
            return obj.isoformat()
        if isinstance(obj, timedelta):
            return str(obj.total_seconds())
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, (bytes, bytearray, memoryview)):
            # Base64 so that arbitrary (non-UTF8) binary data is encodable.
            return b64encode(bytes(obj)).decode("ascii")
        if isinstance(obj, File):
            return obj.name
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, models.Model):
            return obj.pk
        if isinstance(obj, models.QuerySet):
            return list(obj.values_list("pk", flat=True))

        return super().default(obj)


class Decoder(JSONDecoder):
    """Default JSON decoder; values are converted back to Python objects
    by ``FieldLog.from_db``."""


def _load_class(key: str, default: type) -> type:
    path = get_settings().get(key)
    return import_string(path) if path else default


ENCODER = _load_class("ENCODER", Encoder)
DECODER = _load_class("DECODER", Decoder)
