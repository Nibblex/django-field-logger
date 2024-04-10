from datetime import timedelta
from decimal import Decimal
from importlib import reload
from shutil import rmtree
from uuid import UUID

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from fieldlogger import config

now = timezone.now()


CREATE_FORM = {
    "test_big_integer_field": 1,
    "test_binary_field": bytes("test", "utf-8"),
    "test_boolean_field": True,
    "test_char_field": "test",
    "test_date_field": now.date(),
    "test_datetime_field": now,
    "test_decimal_field": Decimal(3.1499),
    "test_duration_field": timedelta(days=1),
    "test_email_field": "test@test.com",
    "test_file_field": ContentFile("test", "test.txt"),
    "test_file_path_field": "test.txt",
    "test_float_field": 1.0,
    "test_generic_ip_address_field": "127.0.0.1",
    "test_image_field": ContentFile("test", "test.txt"),
    "test_integer_field": 1,
    "test_json_field": {"test": "test"},
    "test_positive_big_integer_field": 1,
    "test_positive_integer_field": 1,
    "test_positive_small_integer_field": 1,
    "test_slug_field": "test",
    "test_small_integer_field": 1,
    "test_text_field": "test",
    "test_time_field": now.time(),
    "test_url_field": "https://test.com",
    "test_uuid_field": UUID("550e8400-e29b-41d4-a716-446655440000"),
}

UPDATE_FORM = {
    "test_big_integer_field": 2,
    "test_binary_field": bytes("test2", "utf-8"),
    "test_boolean_field": False,
    "test_char_field": "test2",
    "test_date_field": now.date() + timedelta(days=1),
    "test_datetime_field": now + timedelta(days=1),
    "test_decimal_field": Decimal(3.1415),
    "test_duration_field": timedelta(days=2),
    "test_email_field": "test2@test.com",
    "test_file_field": ContentFile("test2", "test2.txt"),
    "test_file_path_field": "test2.txt",
    "test_float_field": 2.0,
    "test_generic_ip_address_field": "127.0.0.2",
    "test_image_field": ContentFile("test2", "test2.txt"),
    "test_integer_field": 2,
    "test_json_field": {"test": "test2"},
    "test_positive_big_integer_field": 2,
    "test_positive_integer_field": 2,
    "test_positive_small_integer_field": 2,
    "test_slug_field": "test2",
    "test_small_integer_field": 2,
    "test_text_field": "test2",
    "test_time_field": (now + timedelta(hours=1)).time(),
    "test_url_field": "https://test2.com",
    "test_uuid_field": UUID("550e8400-e29b-41d4-a716-446655440001"),
}


def _set_config(cfg, scope):
    for name, value in cfg.items():
        if scope == "global":
            settings.FIELD_LOGGER_SETTINGS[name.upper()] = value
        elif scope == "testapp":
            settings.FIELD_LOGGER_SETTINGS["LOGGING_APPS"]["testapp"][name] = value
        elif scope == "testmodel":
            settings.FIELD_LOGGER_SETTINGS["LOGGING_APPS"]["testapp"]["models"][
                "TestModel"
            ][name] = value
        else:
            raise ValueError(f"Invalid scope: {scope}")

    reload(config)


def set_attributes(instance, form, update_fields=False):
    for field, value in form.items():
        setattr(instance, field, value)
        if update_fields:
            instance.save(update_fields=[field])

    if not update_fields:
        instance.save()

    rmtree(settings.MEDIA_ROOT, ignore_errors=True)


def check_logs(instance, created=False):
    logs = instance.fieldlog_set.filter(created=created)
    assert logs.count() == len(CREATE_FORM if created else UPDATE_FORM)

    for log in logs:
        prev_log = log.previous_log
        assert (prev_log is not None) == (not created)
        assert log.app_label == "testapp"
        assert log.model == "testmodel"
        assert log.instance_id == instance.pk
        assert log.old_value == (prev_log.new_value if prev_log else None)
        assert log.new_value == getattr(instance, log.field)
        assert log.extra_data == {"global": True, "testapp": True}
        assert log.created == created
