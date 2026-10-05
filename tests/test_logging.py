import pytest

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

# CREATE_FORM/UPDATE_FORM plus the test_related_field foreign key.
CREATE_LOG_COUNT = len(CREATE_FORM) + 1
UPDATE_LOG_COUNT = len(UPDATE_FORM) + 1


@pytest.fixture
def update_form():
    return {**UPDATE_FORM, "test_related_field": TestModelRelated.objects.create()}


@pytest.fixture
def test_instance():
    return TestModel.objects.create(
        **CREATE_FORM, test_related_field=TestModelRelated.objects.create()
    )


@pytest.mark.django_db(transaction=True)
class TestCase1:
    def test_log_on_create(self, test_instance):
        check_logs(test_instance, CREATE_LOG_COUNT, created=True)
        check_logs(test_instance, 0)

    @pytest.mark.parametrize("update_fields", [False, True])
    def test_log_on_save(self, test_instance, update_form, update_fields):
        set_attributes(test_instance, update_form, update_fields)

        check_logs(test_instance, UPDATE_LOG_COUNT)

    @pytest.mark.parametrize("update_fields", [False, True])
    def test_log_on_save_twice(self, test_instance, update_form, update_fields):
        set_attributes(test_instance, update_form, update_fields)
        set_attributes(test_instance, update_form, update_fields)

        check_logs(test_instance, UPDATE_LOG_COUNT)


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
def test_instances(log_fields, run_callbacks, ignore_conflicts):
    related_instance = TestModelRelated.objects.create()

    return TestModel.objects.bulk_create(
        [
            TestModel(test_related_field=related_instance, **CREATE_FORM)
            for _ in range(5)
        ],
        log_fields=log_fields,
        run_callbacks=run_callbacks,
        ignore_conflicts=ignore_conflicts,
    )


def bulk_update(instances, update_form, log_fields, run_callbacks):
    bulk_set_attributes(instances, update_form, save=False)
    TestModel.objects.bulk_update(
        instances,
        update_form.keys(),
        log_fields=log_fields,
        run_callbacks=run_callbacks,
    )


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("log_fields", [True, False])
@pytest.mark.parametrize("run_callbacks", [True, False])
@pytest.mark.parametrize("ignore_conflicts", [False, True])
class TestCase3:
    def test_log_on_bulk_create(self, test_instances, log_fields, run_callbacks):
        expected_count = CREATE_LOG_COUNT if log_fields else 0
        bulk_check_logs(test_instances, expected_count, run_callbacks, created=True)
        bulk_check_logs(test_instances, 0, run_callbacks)

    def test_log_on_bulk_update(
        self, test_instances, update_form, log_fields, run_callbacks
    ):
        bulk_update(test_instances, update_form, log_fields, run_callbacks)

        expected_count = UPDATE_LOG_COUNT if log_fields else 0
        bulk_check_logs(test_instances, expected_count, run_callbacks)

    def test_log_on_bulk_update_twice(
        self, test_instances, update_form, log_fields, run_callbacks
    ):
        bulk_update(test_instances, update_form, log_fields, run_callbacks)
        bulk_update(test_instances, update_form, log_fields, run_callbacks)

        expected_count = UPDATE_LOG_COUNT if log_fields else 0
        bulk_check_logs(test_instances, expected_count, run_callbacks)
