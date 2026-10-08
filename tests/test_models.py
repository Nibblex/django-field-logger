from decimal import Decimal

import pytest
from django.db import models

from fieldlogger.models import FieldLog

from .helpers import CREATE_FORM
from .testapp.models import TestModel, TestModelRelated, TestModelRelated2


@pytest.fixture
def test_instance():
    return TestModel.objects.create(**CREATE_FORM)


@pytest.mark.django_db
class TestFieldLog:
    def test_str_shows_field_and_value_change(self, test_instance):
        log = test_instance.fieldlog_set.get(field="test_char_field")
        assert str(log) == (
            "(testapp__testmodel__test_char_field, created=True) None -> test"
        )

    def test_model_returns_logged_model_class(self, test_instance):
        log = test_instance.fieldlog_set.first()
        assert log.model is TestModel

    def test_instance_returns_logged_instance(self, test_instance):
        log = test_instance.fieldlog_set.first()
        assert log.instance == test_instance

    @pytest.mark.parametrize("created", [False, True])
    def test_log_of_removed_field_keeps_json_values(self, created):
        """Logs whose field no longer exists are left as decoded JSON,
        except old_value of creation logs, which is always None."""
        log = FieldLog.objects.create(
            app_label="testapp",
            model_name="testmodel",
            instance_id="1",
            field="removed_field",
            old_value="old",
            new_value="new",
            created=created,
        )

        log = FieldLog.objects.get(pk=log.pk)
        assert log.new_value == "new"
        assert log.old_value == (None if created else "old")

    def test_log_of_reverse_relation_keeps_json_values(self):
        """Reverse relations are never logged; a log naming one is left as
        decoded JSON instead of being converted."""
        log = FieldLog.objects.create(
            app_label="testapp",
            model_name="testmodelrelated",
            instance_id="1",
            # Reverse side of TestModel.test_related_field.
            field="testmodel",
            old_value=[1],
            new_value=[1, 2],
        )

        log = FieldLog.objects.get(pk=log.pk)
        assert log.old_value == [1]
        assert log.new_value == [1, 2]

    def test_related_field_path_resolves_to_related_model(self, test_instance):
        related_instance = TestModelRelated.objects.create(test_char_field="related")

        log = FieldLog.objects.create(
            app_label="testapp",
            model_name="testmodel",
            instance_id=str(test_instance.pk),
            field="test_related_field__test_char_field",
            new_value=related_instance.test_char_field,
            created=True,
        )

        log = FieldLog.objects.get(pk=log.pk)
        assert log.new_value == "related"
        assert log.instance_id == test_instance.pk

    def test_values_are_not_converted_when_fields_are_deferred(self, test_instance):
        """Value conversion is skipped when the needed fields are deferred."""
        log = test_instance.fieldlog_set.get(field="test_decimal_field")
        assert isinstance(log.new_value, Decimal)

        deferred_log = FieldLog.objects.only("pk").get(pk=log.pk)
        assert isinstance(deferred_log.new_value, float)
        assert deferred_log.new_value == float(log.new_value)

    def test_null_foreign_key_converts_to_none(self):
        field = TestModel._meta.get_field("test_related_field")
        assert FieldLog.from_db_field(field, None) is None

    def test_decimal_string_rounds_to_field_places(self):
        field = TestModel._meta.get_field("test_decimal_field")
        assert FieldLog.from_db_field(field, "3.14159") == Decimal("3.14")

    @pytest.mark.parametrize("created", [False, True])
    def test_log_of_removed_model_keeps_json_values(self, created):
        """Logs whose model no longer exists are left as decoded JSON."""
        log = FieldLog.objects.create(
            app_label="testapp",
            model_name="removedmodel",
            instance_id="1",
            field="removed_field",
            old_value="old",
            new_value="new",
            created=created,
        )

        log = FieldLog.objects.get(pk=log.pk)
        assert log.new_value == "new"
        assert log.old_value == (None if created else "old")
        assert log.instance_id == "1"

    def test_one_to_one_values_resolve_to_instances(self):
        """OneToOneField values are converted like any foreign key."""
        related_instance = TestModelRelated2.objects.create()
        instance = TestModel.objects.create(test_one_to_one_field=related_instance)

        log = instance.fieldlog_set.get(field="test_one_to_one_field")
        assert log.new_value == related_instance

    def test_foreign_key_values_are_lazy(self, django_assert_num_queries):
        """Loading logs does not query one related instance per row."""
        related_instance = TestModelRelated.objects.create()
        instance = TestModel.objects.create(test_related_field=related_instance)
        log_pk = instance.fieldlog_set.get(field="test_related_field").pk

        with django_assert_num_queries(1):
            log = FieldLog.objects.get(pk=log_pk)

        with django_assert_num_queries(1):
            assert log.new_value == related_instance

    def test_foreign_key_value_on_deleted_related_instance(self):
        """A logged foreign key whose instance was deleted resolves to an
        unsaved shell instance carrying the primary key."""
        related_instance = TestModelRelated.objects.create()
        instance = TestModel.objects.create(test_related_field=related_instance)
        log_pk = instance.fieldlog_set.get(field="test_related_field").pk
        related_pk = related_instance.pk

        related_instance.delete()

        log = FieldLog.objects.get(pk=log_pk)
        assert isinstance(log.new_value, TestModelRelated)
        assert log.new_value.pk == related_pk

    def test_binary_field_roundtrip_on_non_utf8_bytes(self):
        instance = TestModel.objects.create(test_binary_field=b"\xff\x00\xfe")
        log = instance.fieldlog_set.get(field="test_binary_field")
        assert log.new_value == b"\xff\x00\xfe"

    def test_binary_field_on_legacy_plain_text_value(self):
        """Logs written before binary values were base64-encoded fall back
        to encoding the stored text as utf-8."""
        log = FieldLog.objects.create(
            app_label="testapp",
            model_name="testmodel",
            instance_id="1",
            field="test_binary_field",
            new_value="tests",  # not valid base64
            created=True,
        )

        log = FieldLog.objects.get(pk=log.pk)
        assert log.new_value == b"tests"

    def test_previous_log_links_logs_of_same_field(self):
        instance = TestModel.objects.create(test_char_field="first")
        instance.test_char_field = "second"
        instance.save()
        instance.test_char_field = "third"
        instance.save()

        first, second, third = instance.fieldlog_set.filter(
            field="test_char_field"
        ).order_by("pk")

        assert first.previous_log is None
        assert second.previous_log == first
        assert third.previous_log == second


def test_primary_key_matches_the_migrations():
    """A BigAutoField on every Django version: 3.1 ignored the app's
    default_auto_field and created an AutoField, so makemigrations wanted
    to alter the column of an installed app."""
    pk = FieldLog._meta.pk
    assert type(pk) is models.BigAutoField
    assert pk.auto_created


def test_no_auto_field_warning():
    # The model's own checks, without the database ones (Django 6.1 runs
    # those through run_checks).
    assert not [w for w in FieldLog.check() if w.id == "models.W042"]
