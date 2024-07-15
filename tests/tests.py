from copy import deepcopy
from importlib import reload

import pytest

from django.conf import settings

from fieldlogger import config, signals

from .helpers import CREATE_FORM, UPDATE_FORM, check_logs, set_attributes, set_config
from .testapp.models import TestModel

ORIGINAL_SETTINGS = deepcopy(settings.FIELD_LOGGER_SETTINGS)


@pytest.fixture
def test_instance():
    # Create two instances for the foreign key field
    CREATE_FORM["test_foreign_key"] = TestModel.objects.create()
    UPDATE_FORM["test_foreign_key"] = TestModel.objects.create()

    # Create the main instance
    yield TestModel.objects.create(**CREATE_FORM)


@pytest.mark.django_db
class TestCase:
    def test_log_on_create(self, test_instance):
        check_logs(test_instance, expected_count=len(CREATE_FORM), created=True)

    def test_log_on_save(self, test_instance):
        set_attributes(test_instance, UPDATE_FORM)
        check_logs(test_instance, expected_count=len(CREATE_FORM) + len(UPDATE_FORM))

    def test_log_on_save_twice(self, test_instance):
        set_attributes(test_instance, UPDATE_FORM, update_fields=True)
        set_attributes(test_instance, UPDATE_FORM)
        check_logs(test_instance, expected_count=len(CREATE_FORM) + len(UPDATE_FORM))


@pytest.fixture
def restore_settings():
    yield
    settings.FIELD_LOGGER_SETTINGS = deepcopy(ORIGINAL_SETTINGS)
    reload(config)
    reload(signals)


@pytest.mark.django_db
@pytest.mark.usefixtures("restore_settings")
class TestCase2:
    @pytest.mark.parametrize("scope", ["global", "testapp", "testmodel"])
    def test_logging_disabled(self, scope):
        set_config({"logging_enabled": False}, scope)
        test_instance = TestModel.objects.create(**CREATE_FORM)
        check_logs(test_instance, expected_count=0, created=True)

    @pytest.mark.parametrize("scope", ["global", "testapp", "testmodel"])
    def test_fail_silently(self, scope):
        set_config({"fail_silently": False, "callbacks": [lambda *args: 1 / 0]}, scope)
        with pytest.raises(ZeroDivisionError):
            TestModel.objects.create(**CREATE_FORM)


@pytest.mark.django_db
class TestCase3:
    def test_log_on_bulk_create(self):
        TestModel.objects.bulk_create([TestModel(**CREATE_FORM) for _ in range(5)])

        for instance in TestModel.objects.all():
            check_logs(instance, expected_count=len(CREATE_FORM), created=True)
