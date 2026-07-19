import django
import pytest
from django.conf import settings
from django.test import override_settings

from fieldlogger import config

from .helpers import CREATE_FORM, check_logs, refresh_config, set_config
from .testapp.models import TestModel


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("restore_settings")
class TestConfig:
    def test_fields_list(self):
        """Only the listed fields are logged; unknown names are ignored."""
        set_config({"fields": ["test_char_field", "nonexistent_field"]}, "testmodel")

        instance = TestModel.objects.create(**CREATE_FORM)
        check_logs(instance, expected_count=1, created=True)
        assert instance.fieldlog_set.get().field == "test_char_field"

    def test_unknown_model_is_skipped(self):
        settings.FIELD_LOGGER_SETTINGS["LOGGING_APPS"]["testapp"]["models"][
            "NoSuchModel"
        ] = {"fields": "__all__"}
        refresh_config()

        assert set(config.get_config()) == {TestModel}

    def test_logging_fields_are_concrete(self):
        """Reverse relations and many-to-many fields returned by
        get_fields() have no column, so they are not logged."""
        logging_fields = config.get_config()[TestModel]["logging_fields"]
        names = {field.name for field in logging_fields}

        assert all(field.concrete for field in logging_fields)
        assert "testmodelrelated2" not in names
        assert "test_many_to_many_field" not in names

    @pytest.mark.skipif(
        django.VERSION < (5, 0), reason="GeneratedField requires Django 5.0"
    )
    def test_generated_fields_are_not_logged(self):
        """Database-generated values may be stale in memory after an
        update, so GeneratedField is never logged."""
        logging_fields = config.get_config()[TestModel]["logging_fields"]
        assert "test_generated_field" not in {field.name for field in logging_fields}

        instance = TestModel.objects.create(test_integer_field=1)
        instance.test_integer_field = 2
        instance.save()

        assert not instance.fieldlog_set.filter(field="test_generated_field").exists()
        assert instance.fieldlog_set.filter(field="test_integer_field").count() == 2

    def test_falsy_configs_are_skipped(self):
        settings.FIELD_LOGGER_SETTINGS["LOGGING_APPS"]["emptyapp"] = None
        settings.FIELD_LOGGER_SETTINGS["LOGGING_APPS"]["testapp"]["models"][
            "TestModelRelated"
        ] = None
        refresh_config()

        assert set(config.get_config()) == {TestModel}

    def test_override_settings_rebuilds_config(self):
        """Overriding FIELD_LOGGER_SETTINGS rebuilds the configuration
        without any manual invalidation."""
        with override_settings(FIELD_LOGGER_SETTINGS={}):
            assert config.get_config() == {}

        assert TestModel in config.get_config()
