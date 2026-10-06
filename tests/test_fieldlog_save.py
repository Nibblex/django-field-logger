"""Saving an existing log must not rewrite its logged values: once loaded
they hold converted objects (e.g. related instances) that Django refuses to
write to a JSON column."""

from decimal import Decimal

import pytest

from fieldlogger.models import FieldLog

from .testapp.models import TestModel, TestModelRelated


def stored_values(log):
    """Stored (old_value, new_value, extra_data["seen"]); the default test
    callbacks add their own keys to extra_data."""
    old_value, new_value, extra_data = (
        FieldLog.objects.filter(pk=log.pk)
        .values_list("old_value", "new_value", "extra_data")
        .get()
    )
    return old_value, new_value, extra_data.get("seen")


@pytest.mark.django_db(transaction=True)
class TestFullSave:
    def test_callback_can_save_a_foreign_key_log(self, settings):
        def callback(instance, logging_fields, logs):
            log = logs["test_related_field"]
            log.extra_data["seen"] = True
            log.save()

        settings.FIELD_LOGGER_SETTINGS = {
            "LOGGING_APPS": {
                "testapp": {
                    "callbacks": [callback],
                    "models": {
                        "TestModel": {
                            "fields": ["test_related_field"],
                            # Surface callback errors instead of logging them.
                            "fail_silently": False,
                        }
                    },
                }
            }
        }
        related = TestModelRelated.objects.create()

        instance = TestModel.objects.create(test_related_field=related)

        log = instance.fieldlog_set.get(field="test_related_field")
        assert stored_values(log) == (None, related.pk, True)

    @pytest.mark.parametrize(
        "field, value, stored",
        [
            ("test_related_field", None, None),  # replaced by an instance below
            ("test_decimal_field", Decimal("3.1499"), 3.15),
            ("test_binary_field", b"\xff\x00", "/wA="),
        ],
        ids=["foreign-key", "decimal", "binary"],
    )
    def test_loaded_log_saves_without_rewriting_values(self, field, value, stored):
        if field == "test_related_field":
            value = TestModelRelated.objects.create()
            stored = value.pk
        instance = TestModel.objects.create(**{field: value})

        log = FieldLog.objects.get(pk=instance.fieldlog_set.get(field=field).pk)
        log.extra_data["seen"] = True
        log.save()

        assert stored_values(log) == (None, stored, True)

    def test_deferred_fields_are_not_fetched(self, django_assert_num_queries):
        instance = TestModel.objects.create(test_char_field="x")
        log = FieldLog.objects.only("pk", "extra_data").get(
            pk=instance.fieldlog_set.get(field="test_char_field").pk
        )
        log.extra_data["seen"] = True

        with django_assert_num_queries(1):
            log.save()

        assert stored_values(log) == (None, "x", True)

    def test_explicit_update_fields_can_rewrite_values(self):
        instance = TestModel.objects.create(test_char_field="x")
        log = instance.fieldlog_set.get(field="test_char_field")

        log.new_value = "y"
        log.save(update_fields=["new_value"])

        assert stored_values(log)[1] == "y"

    def test_new_logs_are_saved_with_their_values(self):
        log = FieldLog(
            app_label="testapp",
            model_name="testmodel",
            instance_id="1",
            field="test_char_field",
            new_value="x",
        )
        log.save()

        assert stored_values(log) == (None, "x", None)
