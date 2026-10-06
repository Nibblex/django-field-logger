"""Logged values are the ones stored in the database, not the ones held in
memory, which may be expressions or differ from what the database keeps."""

from decimal import Decimal

import django
import pytest
from django.db import connection
from django.db.models import F, Value
from django.db.models.functions import Concat, Upper
from django.test.utils import CaptureQueriesContext

from .testapp.models import TestModel, TestModelRelated


def field_logs(instance, field):
    return list(
        instance.fieldlog_set.filter(field=field)
        .order_by("pk")
        .values_list("created", "old_value", "new_value")
    )


@pytest.mark.django_db(transaction=True)
class TestSave:
    def test_decimal_is_logged_as_rounded_by_the_database(self):
        instance = TestModel.objects.create(test_decimal_field=Decimal("3.1499"))

        assert field_logs(instance, "test_decimal_field") == [(True, None, 3.15)]

    def test_resaving_an_unrounded_decimal_logs_no_change(self):
        instance = TestModel.objects.create(test_decimal_field=Decimal("3.1499"))
        instance.save()

        assert len(field_logs(instance, "test_decimal_field")) == 1

    def test_f_expression_is_logged_as_the_resulting_value(self):
        instance = TestModel.objects.create(test_integer_field=1)
        instance.test_integer_field = F("test_integer_field") + 1
        instance.save()

        assert field_logs(instance, "test_integer_field") == [
            (True, None, 1),
            (False, 1, 2),
        ]

    def test_database_function_is_logged_as_the_resulting_value(self):
        instance = TestModel.objects.create(test_char_field="abc")
        instance.test_char_field = Upper("test_char_field")
        instance.save(update_fields=["test_char_field"])

        assert field_logs(instance, "test_char_field")[-1] == (False, "abc", "ABC")

    def test_expression_on_create_is_logged_as_the_resulting_value(self):
        instance = TestModel.objects.create(
            test_char_field=Concat(Value("a"), Value("b"))
        )

        assert field_logs(instance, "test_char_field") == [(True, None, "ab")]

    def test_empty_file_field_is_not_logged(self):
        instance = TestModel.objects.create(test_char_field="x")
        instance.save()

        assert field_logs(instance, "test_file_field") == []

    def test_foreign_keys_are_compared_without_fetching_related_instances(self):
        instance = TestModel.objects.create(
            test_related_field=TestModelRelated.objects.create()
        )
        instance = TestModel.objects.get(pk=instance.pk)
        instance.test_char_field = "changed"

        with CaptureQueriesContext(connection) as queries:
            instance.save()

        related_table = TestModelRelated._meta.db_table
        assert not [q for q in queries if f'FROM "{related_table}"' in q["sql"]]

    def test_callbacks_get_values_as_loaded_from_the_database(self, settings):
        received = {}

        def callback(instance, logging_fields, logs):
            received.update(logs)

        settings.FIELD_LOGGER_SETTINGS = {
            "LOGGING_APPS": {
                "testapp": {
                    "callbacks": [callback],
                    "models": {"TestModel": {"fields": ["test_related_field"]}},
                }
            }
        }
        related = TestModelRelated.objects.create()

        TestModel.objects.create(test_related_field=related)

        assert received["test_related_field"].new_value == related


@pytest.mark.skipif(django.VERSION < (5, 0), reason="db_default requires Django 5.0")
@pytest.mark.django_db(transaction=True)
def test_db_default_is_logged_as_the_stored_value(settings):
    settings.FIELD_LOGGER_SETTINGS = {
        "LOGGING_APPS": {
            "testapp": {
                "models": {"TestModelRelated": {"fields": ["test_db_default_field"]}}
            }
        }
    }

    instance = TestModelRelated.objects.create()

    assert field_logs(instance, "test_db_default_field") == [(True, None, 7)]


@pytest.mark.django_db(transaction=True)
class TestBulk:
    def test_bulk_update_with_expression_is_logged(self):
        instance = TestModel.objects.create(test_integer_field=1)
        instance.test_integer_field = F("test_integer_field") + 1

        TestModel.objects.bulk_update([instance], ["test_integer_field"])

        assert field_logs(instance, "test_integer_field")[-1] == (False, 1, 2)

    def test_bulk_create_logs_decimal_as_rounded(self):
        (instance,) = TestModel.objects.bulk_create(
            [TestModel(test_decimal_field=Decimal("3.1499"))]
        )

        assert field_logs(instance, "test_decimal_field") == [(True, None, 3.15)]
