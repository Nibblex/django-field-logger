from copy import deepcopy
from importlib import reload

import pytest

from django.conf import settings

from fieldlogger import config

from .helpers import (
    CREATE_FORM,
    UPDATE_FORM,
    bulk_set_attributes,
    check_logs,
    set_attributes,
    set_config,
)
from .testapp.models import TestModel, TestModelRelated

ORIGINAL_SETTINGS = deepcopy(settings.FIELD_LOGGER_SETTINGS)


@pytest.fixture
def test_instance():
    related_instance = TestModelRelated.objects.create()

    UPDATE_FORM["test_related_field"] = TestModelRelated.objects.create()

    return TestModel.objects.create(test_related_field=related_instance, **CREATE_FORM)


@pytest.mark.django_db(transaction=True)
class TestCase1:
    def test_log_on_direct_fields(self, test_instance):
        check_logs(test_instance, expected_count=len(CREATE_FORM) + 1, created=True)

    @pytest.mark.parametrize("update_fields", [False, True])
    def test_log_on_save(self, test_instance, update_fields):
        set_attributes(test_instance, UPDATE_FORM, update_fields)
        check_logs(test_instance, expected_count=len(CREATE_FORM) + len(UPDATE_FORM) + 1)

    @pytest.mark.parametrize("update_fields", [False, True])
    def test_log_on_save_twice(self, test_instance, update_fields):
        set_attributes(test_instance, UPDATE_FORM, update_fields)
        set_attributes(test_instance, UPDATE_FORM, update_fields)
        check_logs(test_instance, expected_count=len(CREATE_FORM) + len(UPDATE_FORM) + 1)


@pytest.fixture
def restore_settings():
    yield
    settings.FIELD_LOGGER_SETTINGS = deepcopy(ORIGINAL_SETTINGS)
    reload(config)


@pytest.mark.django_db(transaction=True)
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("log_fields", [True, False])
@pytest.mark.parametrize("run_callbacks", [True, False])
class TestCase3:
    def test_log_on_bulk_create(self, log_fields, run_callbacks):
        TestModel.objects.bulk_create(
            [TestModel(**CREATE_FORM) for _ in range(5)],
            log_fields=log_fields,
            run_callbacks=run_callbacks,
        )

        for instance in TestModel.objects.all():
            check_logs(
                instance,
                expected_count=len(CREATE_FORM) if log_fields else 0,
                extra_data=None if run_callbacks else {},
                created=True,
            )

    def test_log_on_bulk_update(self, test_instance, log_fields, run_callbacks):
        instances = [TestModel.objects.create(**CREATE_FORM) for _ in range(5)]
        bulk_set_attributes(instances, UPDATE_FORM, save=False)

        TestModel.objects.bulk_update(
            instances,
            fields=UPDATE_FORM.keys(),
            log_fields=log_fields,
            run_callbacks=run_callbacks,
        )

        expected_count = (
            len(CREATE_FORM) + len(UPDATE_FORM) if log_fields else len(CREATE_FORM)
        )

        for instance in instances:
            check_logs(
                instance,
                expected_count=expected_count,
                extra_data=None if run_callbacks else {},
            )
