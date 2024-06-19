import logging
from copy import deepcopy
from importlib import reload

import pytest

from django.conf import settings

from fieldlogger import config, fieldlogger, signals

from .helpers import CREATE_FORM, UPDATE_FORM, check_logs, set_attributes, set_config
from .testapp.models import TestModel, TestModelRelated, TestModelRelated2

ORIGINAL_SETTINGS = deepcopy(settings.FIELD_LOGGER_SETTINGS)


@pytest.fixture
def test_instance():
    related_instance = TestModelRelated.objects.create()

    UPDATE_FORM["test_related_field"] = TestModelRelated.objects.create()

    return TestModel.objects.create(test_related_field=related_instance, **CREATE_FORM)


@pytest.mark.django_db
class TestCase1:
    def test_log_on_direct_fields(self, test_instance):
        check_logs(test_instance, expected_count=len(CREATE_FORM) + 1, created=True)

    @pytest.mark.parametrize("update_fields", [False, True])
    def test_log_on_save(self, test_instance, update_fields):
        logging.info(f"\ntest_log_on_save, {update_fields}")
        set_attributes(test_instance, UPDATE_FORM, update_fields)
        check_logs(test_instance, expected_count=len(CREATE_FORM) + len(UPDATE_FORM) + 1)

    @pytest.mark.parametrize("update_fields", [False, True])
    def test_log_on_save_twice(self, test_instance, update_fields):
        set_attributes(test_instance, UPDATE_FORM, update_fields)
        set_attributes(test_instance, UPDATE_FORM, update_fields)
        check_logs(test_instance, expected_count=len(CREATE_FORM) + len(UPDATE_FORM) + 1)

    @pytest.mark.parametrize("update_fields", [False, True])
    def test_log_on_related_fields(self, test_instance, update_fields):
        set_attributes(
            test_instance.test_related_field, {"test_char_field": "test2"}, update_fields
        )
        set_attributes(
            test_instance.test_related_field,
            {
                "test_related_field2": TestModelRelated2.objects.create(
                    test_char_field="test"
                )
            },
            update_fields,
        )
        set_attributes(
            test_instance.test_related_field.test_related_field2,
            {"test_char_field": "test2"},
            update_fields,
        )
        set_attributes(
            test_instance.test_related_field.test_related_field2,
            {"test_related_field3": TestModel.objects.create(test_char_field="test")},
            update_fields,
        )
        set_attributes(
            test_instance.test_related_field.test_related_field2.test_related_field3,
            {"test_char_field": "test2"},
            update_fields,
        )

        for log in test_instance.fieldlog_set.filter(created=False):
            if update_fields:
                logging.info(f"{log.extra_data}, {log}\n")


@pytest.fixture
def restore_settings():
    yield
    settings.FIELD_LOGGER_SETTINGS = deepcopy(ORIGINAL_SETTINGS)
    reload(config)
    reload(signals)
    reload(fieldlogger)


@pytest.mark.django_db
@pytest.mark.usefixtures("restore_settings")
@pytest.mark.parametrize("scope", ["global", "testapp", "testmodel"])
class TestCase2:
    def test_logging_disabled(self, scope):
        set_config({"logging_enabled": False}, scope)
        test_instance = TestModel.objects.create(**CREATE_FORM)
        check_logs(test_instance, expected_count=0, created=True)

    def test_fail_silently(self, scope):
        set_config({"fail_silently": False, "callbacks": [lambda *args: 1 / 0]}, scope)
        with pytest.raises(ZeroDivisionError):
            TestModel.objects.create(**CREATE_FORM)
