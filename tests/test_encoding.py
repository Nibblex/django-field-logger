from base64 import b64encode
from importlib import reload
from json import JSONDecoder, JSONEncoder

import pytest
from django.conf import settings

from fieldlogger import encoding

from .testapp.models import TestModelRelated


class CustomEncoder(JSONEncoder):
    pass


class CustomDecoder(JSONDecoder):
    pass


class TestEncoder:
    @pytest.mark.django_db
    def test_queryset(self):
        related_instance = TestModelRelated.objects.create()
        encoded = encoding.Encoder().default(TestModelRelated.objects.all())
        assert encoded == [related_instance.pk]

    def test_unsupported_type(self):
        with pytest.raises(TypeError):
            encoding.Encoder().default(object())

    def test_non_utf8_bytes(self):
        raw = b"\xff\x00\xfe"
        assert encoding.Encoder().default(raw) == b64encode(raw).decode("ascii")


def test_custom_encoder_decoder_settings():
    settings.FIELD_LOGGER_SETTINGS["ENCODER"] = "tests.test_encoding.CustomEncoder"
    settings.FIELD_LOGGER_SETTINGS["DECODER"] = "tests.test_encoding.CustomDecoder"

    try:
        reload(encoding)
        assert encoding.ENCODER is CustomEncoder
        assert encoding.DECODER is CustomDecoder
    finally:
        del settings.FIELD_LOGGER_SETTINGS["ENCODER"]
        del settings.FIELD_LOGGER_SETTINGS["DECODER"]
        reload(encoding)

    assert encoding.ENCODER is encoding.Encoder
    assert encoding.DECODER is encoding.Decoder
