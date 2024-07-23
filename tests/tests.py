from copy import deepcopy
from importlib import reload

import pytest

from django.conf import settings

from fieldlogger import config

from .helpers import (
    CREATE_FORM,
    UPDATE_FORM,
    bulk_check_logs,
    bulk_set_attributes,
    check_logs,
    set_attributes,
    set_config,
)
from .testapp.models import TestModel, TestModelRelated

ORIGINAL_SETTINGS = deepcopy(settings.FIELD_LOGGER_SETTINGS)


@pytest.fixture
def test_instance(expected_count):
    UPDATE_FORM["test_related_field"] = TestModelRelated.objects.create()

    instance = TestModel.objects.create(
        **CREATE_FORM, test_related_field=TestModelRelated.objects.create()
    )

    check_logs(instance, len(CREATE_FORM) + 1, created=True)
    yield instance
    check_logs(instance, expected_count)


@pytest.mark.django_db(transaction=True)
class TestCase1:
    @pytest.mark.parametrize("test_instance", [(0, True)], indirect=True)
    @pytest.mark.parametrize("expected_count", [0])
    def test_log_on_direct_fields(self, test_instance, expected_count):
        pass

    @pytest.mark.parametrize("update_fields", [False, True])
    @pytest.mark.parametrize("expected_count", [len(UPDATE_FORM)])
    def test_log_on_save(self, test_instance, update_fields, expected_count):
        set_attributes(test_instance, UPDATE_FORM, update_fields)

    @pytest.mark.parametrize("update_fields", [False, True])
    @pytest.mark.parametrize("expected_count", [len(UPDATE_FORM)])
    def test_log_on_save_twice(self, test_instance, update_fields, expected_count):
        set_attributes(test_instance, UPDATE_FORM, update_fields)
        set_attributes(test_instance, UPDATE_FORM, update_fields)


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


@pytest.fixture
def test_instances(expected_count, log_fields, run_callbacks):
    related_instance = TestModelRelated.objects.create()

    UPDATE_FORM["test_related_field"] = TestModelRelated.objects.create()

    instances = TestModel.objects.bulk_create(
        [TestModel(test_related_field=related_instance, **CREATE_FORM) for _ in range(5)],
        log_fields=log_fields,
        run_callbacks=run_callbacks,
    )

    bulk_check_logs(
        instances, len(CREATE_FORM) + 1 if log_fields else 0, run_callbacks, created=True
    )
    yield instances
    bulk_check_logs(instances, expected_count if log_fields else 0, run_callbacks)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("log_fields", [True, False])
@pytest.mark.parametrize("run_callbacks", [True, False])
class TestCase3:
    @pytest.mark.parametrize("expected_count", [0])
    def test_log_on_bulk_create(self, test_instances, log_fields, run_callbacks):
        pass

    @pytest.mark.parametrize("expected_count", [len(UPDATE_FORM)])
    def test_log_on_bulk_update(self, test_instances, log_fields, run_callbacks):
        bulk_set_attributes(test_instances, UPDATE_FORM, save=False)

        TestModel.objects.bulk_update(
            test_instances,
            UPDATE_FORM.keys(),
            log_fields=log_fields,
            run_callbacks=run_callbacks,
        )

    @pytest.mark.parametrize("expected_count", [len(UPDATE_FORM)])
    def test_log_on_bulk_update_twice(self, test_instances, log_fields, run_callbacks):
        bulk_set_attributes(test_instances, UPDATE_FORM, save=False)

        TestModel.objects.bulk_update(
            test_instances,
            UPDATE_FORM.keys(),
            log_fields=log_fields,
            run_callbacks=run_callbacks,
        )

        bulk_set_attributes(test_instances, UPDATE_FORM, save=False)

        TestModel.objects.bulk_update(
            test_instances,
            UPDATE_FORM.keys(),
            log_fields=log_fields,
            run_callbacks=run_callbacks,
        )
