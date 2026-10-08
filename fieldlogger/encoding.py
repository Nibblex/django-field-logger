"""JSON encoding/decoding of logged field values.

Custom classes can be configured through the ``ENCODER`` and ``DECODER``
keys of ``FIELD_LOGGER_SETTINGS`` as dotted import paths. The ``FieldLog``
JSON fields always reference ``Encoder`` and ``Decoder``, which stand in
for the configured classes when instantiated: the fields, and so the
migrations, never depend on the settings, and the settings are read at
use, without a restart.
"""

from base64 import b64encode
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from json import JSONDecoder, JSONEncoder
from typing import Any
from uuid import UUID

from django.core.files import File
from django.db import models
from django.utils.module_loading import import_string

from .app_settings import get_settings


def _configured(key: str, default: type) -> type:
    """The class configured under ``key``, or ``default``."""
    path = get_settings().get(key)
    return import_string(path) if path else default


class Encoder(JSONEncoder):
    """JSON encoder for the value types of the standard Django fields.

    Instantiating it returns the configured ``ENCODER`` instead, if any.
    Custom encoders may subclass it to extend the default handling.
    """

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        configured = _configured("ENCODER", Encoder) if cls is Encoder else cls
        if configured is not cls:
            return configured(*args, **kwargs)
        return super().__new__(cls)

    def default(self, obj: Any) -> Any:
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
    by ``FieldLog.from_db``.

    Instantiating it returns the configured ``DECODER`` instead, if any.
    """

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        configured = _configured("DECODER", Decoder) if cls is Decoder else cls
        if configured is not cls:
            return configured(*args, **kwargs)
        return super().__new__(cls)
