"""Test settings with a custom ENCODER and DECODER (see test_encoding.py)."""

from .settings import *  # noqa: F403

FIELD_LOGGER_SETTINGS = {
    **FIELD_LOGGER_SETTINGS,  # noqa: F405
    "ENCODER": "tests.custom_codec.PointEncoder",
    "DECODER": "tests.custom_codec.PointDecoder",
}
