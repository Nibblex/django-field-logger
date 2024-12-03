from datetime import timedelta
from decimal import Decimal
from importlib import reload
from shutil import rmtree
from uuid import UUID

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone

from fieldlogger import config, fieldlogger, signals

NOW = timezone.now()


CREATE_FORM = {
    "test_big_integer_field": 1,
    "test_binary_field": bytes("test", "utf-8"),
    "test_boolean_field": True,
    "test_char_field": "test",
    "test_date_field": NOW.date(),
    "test_datetime_field": NOW,
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
    "test_time_field": NOW.time(),
    "test_url_field": "https://test.com",
    "test_uuid_field": UUID("550e8400-e29b-41d4-a716-446655440000"),
}

UPDATE_FORM = {
    "test_big_integer_field": 2,
    "test_binary_field": bytes("test2", "utf-8"),
    "test_boolean_field": False,
    "test_char_field": "test2",
    "test_date_field": NOW.date() + timedelta(days=1),
    "test_datetime_field": NOW + timedelta(days=1),
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
    "test_time_field": (NOW + timedelta(hours=1)).time(),
    "test_url_field": "https://test2.com",
    "test_uuid_field": UUID("550e8400-e29b-41d4-a716-446655440001"),
}


def reload_modules():
    reload(config)
    reload(fieldlogger)
    reload(signals)


def set_config(cfg, scope):
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

    reload_modules()


def set_attributes(instance, form, update_fields=False, save=True):
    for field, value in form.items():
        setattr(instance, field, value)
        if update_fields and save:
            instance.save(update_fields=[field])

    if not update_fields and save:
        instance.save()

    rmtree(settings.MEDIA_ROOT, ignore_errors=True)


def bulk_set_attributes(instances, form, update_fields=False, save=True):
    for instance in instances:
        set_attributes(instance, form, update_fields, save)


def check_logs(instance, expected_count, extra_data=True, created=False):
    instance.refresh_from_db()

    logs = instance.fieldlog_set.order_by("-pk")[:expected_count]
    assert logs.count() == expected_count

    _extra_data = {"global": True, "testapp": True, "testmodel": True}

    for log in logs:
        prev_log = log.previous_log
        assert log.app_label == "testapp"
        assert log.model_name == "testmodel"
        assert log.instance_id == instance.pk
        assert log.old_value == (prev_log.new_value if prev_log else None)
        assert log.new_value == getattr(instance, log.field)
        assert log.extra_data == (_extra_data if extra_data else {})
        assert log.created == created


def bulk_check_logs(instances, expected_count, extra_data=True, created=False):
    for instance in instances:
        check_logs(instance, expected_count, extra_data, created)
