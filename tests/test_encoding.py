from base64 import b64encode

import pytest
from django.core.files.base import ContentFile

from fieldlogger import encoding
from fieldlogger.models import FieldLog

from .custom_codec import Point, PointDecoder, PointEncoder
from .helpers import run_python
from .testapp.models import TestModelRelated


class TestEncoder:
    @pytest.mark.django_db
    def test_queryset_encodes_as_pk_list(self):
        related_instance = TestModelRelated.objects.create()
        encoded = encoding.Encoder().default(TestModelRelated.objects.all())
        assert encoded == [related_instance.pk]

    @pytest.mark.django_db
    def test_model_instance_encodes_as_pk(self):
        related_instance = TestModelRelated.objects.create()
        assert encoding.Encoder().default(related_instance) == related_instance.pk

    def test_file_encodes_as_name(self):
        assert encoding.Encoder().default(ContentFile(b"x", name="a.txt")) == "a.txt"

    def test_unsupported_type_raises_type_error(self):
        with pytest.raises(TypeError):
            encoding.Encoder().default(object())

    def test_bytes_encode_as_base64(self):
        raw = b"\xff\x00\xfe"
        assert encoding.Encoder().default(raw) == b64encode(raw).decode("ascii")


@pytest.fixture
def custom_codec(settings):
    settings.FIELD_LOGGER_SETTINGS = {
        **settings.FIELD_LOGGER_SETTINGS,
        "ENCODER": "tests.custom_codec.PointEncoder",
        "DECODER": "tests.custom_codec.PointDecoder",
    }


def test_default_classes_without_settings():
    assert type(encoding.Encoder()) is encoding.Encoder
    assert type(encoding.Decoder()) is encoding.Decoder


@pytest.mark.usefixtures("custom_codec")
def test_configured_classes_stand_in_for_the_defaults():
    """Read at use: overriding the settings needs no restart or reload."""
    assert type(encoding.Encoder(sort_keys=True)) is PointEncoder
    assert encoding.Encoder(sort_keys=True).sort_keys
    assert type(encoding.Decoder()) is PointDecoder
    # Subclasses of Encoder are instantiated as themselves.
    assert type(PointEncoder()) is PointEncoder


@pytest.mark.django_db
@pytest.mark.usefixtures("custom_codec")
def test_configured_classes_are_used_by_fieldlog():
    log = FieldLog.objects.create(
        app_label="testapp",
        model_name="testmodel",
        instance_id="1",
        field="f",
        extra_data={"point": Point(1, 2)},
    )

    assert FieldLog.objects.get(pk=log.pk).extra_data == {"point": Point(1, 2)}


def test_configured_classes_do_not_change_migrations(tmp_path):
    """The JSON fields always reference Encoder/Decoder: configuring other
    classes used to make makemigrations write a migration into the
    installed package."""
    run_python(
        ["-m", "django", "makemigrations", "fieldlogger", "--check", "--dry-run"],
        tmp_path,
        "tests.settings_custom_codec",
    )
