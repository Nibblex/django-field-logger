"""Logging deletions (log_deletions)."""

import re
from decimal import Decimal

import django
import pytest
from django.conf import settings
from django.db import connections
from django.db.models import F
from django.db.models.signals import post_delete, pre_delete
from django.test.utils import CaptureQueriesContext

from fieldlogger import disable_logging, set_actor, set_correlation_id, signals
from fieldlogger.fieldlogger import PRE_DELETE_ATTR, log_deletions
from fieldlogger.masking import MASK
from fieldlogger.models import FieldLog

from .helpers import refresh_config, set_config
from .testapp.models import (
    CustomQuerySetModel,
    TestModel,
    TestModelRelated,
    TestModelRelated2,
)


def deletion_logs(model, pk):
    """{field: (old_value, new_value)} of the deletion logs of the instance
    ``pk`` of ``model``, loaded from the database."""
    logs = FieldLog.objects.filter(
        app_label=model._meta.app_label,
        model_name=model._meta.model_name,
        instance_id=pk,
        deleted=True,
    )
    return {log.field: (log.old_value, log.new_value) for log in logs}


def model_selects(queries, model):
    """The captured queries that read rows of ``model``'s table."""
    table = re.escape(model._meta.db_table)
    return [
        query["sql"]
        for query in queries
        if query["sql"].lstrip().upper().startswith("SELECT")
        and re.search(rf"\bFROM\W+{table}\W", query["sql"], re.IGNORECASE)
    ]


@pytest.fixture
def deletions_logged(restore_settings):
    set_config({"log_deletions": True}, "testmodel")


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("deletions_logged")
class TestLogDeletions:
    def test_fields_with_a_value_are_logged(self):
        instance = TestModel.objects.create(
            test_char_field="last", test_integer_field=1
        )
        pk = instance.pk
        instance.delete()

        assert deletion_logs(TestModel, pk) == {
            "test_char_field": ("last", None),
            "test_integer_field": (1, None),
        }
        log = FieldLog.objects.get(
            instance_id=pk, field="test_char_field", deleted=True
        )
        assert not log.created
        assert not log.masked

    def test_values_are_converted_on_load(self):
        related = TestModelRelated.objects.create()
        instance = TestModel.objects.create(
            test_decimal_field=Decimal("3.14"), test_related_field=related
        )
        pk = instance.pk
        instance.delete()

        logs = deletion_logs(TestModel, pk)
        assert logs["test_decimal_field"] == (Decimal("3.14"), None)
        assert logs["test_related_field"] == (related, None)

    def test_fields_that_reject_no_value_load(self):
        """A BooleanField without null cannot convert None, the new value of
        a deletion."""
        settings.FIELD_LOGGER_SETTINGS["LOGGING_APPS"]["testapp"]["models"][
            "CustomQuerySetModel"
        ] = {"fields": ["deleted"], "log_deletions": True}
        refresh_config()
        instance = CustomQuerySetModel.objects.create()
        pk = instance.pk
        instance.delete()

        assert deletion_logs(CustomQuerySetModel, pk) == {"deleted": (False, None)}

    def test_the_stored_values_are_logged(self):
        """Not the instance's, which holds an expression after saving one."""
        instance = TestModel.objects.create(test_integer_field=1)
        instance.test_integer_field = F("test_integer_field") + 1
        instance.save()
        pk = instance.pk
        instance.delete()

        assert deletion_logs(TestModel, pk) == {"test_integer_field": (2, None)}

    def test_queryset_deletes_are_logged(self):
        instances = [
            TestModel.objects.create(test_char_field=f"last {i}") for i in range(3)
        ]
        TestModel.objects.filter(
            pk__in=[instance.pk for instance in instances]
        ).delete()

        assert [deletion_logs(TestModel, instance.pk) for instance in instances] == [
            {"test_char_field": (f"last {i}", None)} for i in range(3)
        ]

    def test_cascades_are_logged(self):
        related = TestModelRelated.objects.create()
        related_pk = related.pk
        instance = TestModel.objects.create(
            test_char_field="last", test_related_field=related
        )
        related.delete()

        logs = deletion_logs(TestModel, instance.pk)
        assert logs["test_char_field"] == ("last", None)
        # The related instance no longer exists: an unsaved one with its pk.
        assert logs["test_related_field"][0].pk == related_pk

    def test_deleting_an_instance_reads_its_stored_row(self):
        instance = TestModel.objects.create(test_char_field="last")

        with CaptureQueriesContext(connections["default"]) as queries:
            instance.delete()

        assert len(model_selects(queries.captured_queries, TestModel)) == 1

    def test_queryset_deletes_use_the_rows_django_loads(self):
        instances = [TestModel.objects.create(test_char_field="last") for _ in range(3)]

        with CaptureQueriesContext(connections["default"]) as queries:
            TestModel.objects.filter(
                pk__in=[instance.pk for instance in instances]
            ).delete()

        # Django loads the rows to send the signals. Before 4.1 the signals
        # do not tell them apart from an instance's delete(), which reads
        # its row.
        expected = 1 if django.VERSION >= (4, 1) else 1 + len(instances)
        assert len(model_selects(queries.captured_queries, TestModel)) == expected

    def test_deferred_rows_are_read_once(self):
        instance = TestModel.objects.create(
            test_char_field="last", test_integer_field=1
        )

        with CaptureQueriesContext(connections["default"]) as queries:
            TestModel.objects.only("pk").filter(pk=instance.pk).delete()

        assert deletion_logs(TestModel, instance.pk) == {
            "test_char_field": ("last", None),
            "test_integer_field": (1, None),
        }
        assert len(model_selects(queries.captured_queries, TestModel)) == 2

    def test_rows_already_deleted_are_not_logged_again(self):
        instance = TestModel.objects.create(test_char_field="last")
        pk = instance.pk
        TestModel.objects.filter(pk=pk).delete()
        instance.delete()

        assert FieldLog.objects.filter(instance_id=pk, deleted=True).count() == 1

    def test_disable_logging(self):
        instance = TestModel.objects.create(test_char_field="last")
        pk = instance.pk

        with CaptureQueriesContext(connections["default"]) as queries:
            with disable_logging():
                instance.delete()

        assert deletion_logs(TestModel, pk) == {}
        assert model_selects(queries.captured_queries, TestModel) == []

    def test_models_without_logged_fields_are_not_read(self):
        set_config({"fields": ["test_many_to_many_field"]}, "testmodel")
        instance = TestModel.objects.create(test_char_field="last")
        pk = instance.pk

        with CaptureQueriesContext(connections["default"]) as queries:
            instance.delete()

        assert deletion_logs(TestModel, pk) == {}
        assert model_selects(queries.captured_queries, TestModel) == []

    def test_m2m_fields_are_not_logged(self):
        instance = TestModel.objects.create()
        instance.test_many_to_many_field.add(TestModelRelated2.objects.create())
        pk = instance.pk
        instance.delete()

        assert deletion_logs(TestModel, pk) == {}

    def test_masked_fields_are_masked(self):
        set_config({"mask_fields": ["test_char_field"]}, "testmodel")
        instance = TestModel.objects.create(test_char_field="secret")
        pk = instance.pk
        instance.delete()

        log = FieldLog.objects.get(
            instance_id=pk, field="test_char_field", deleted=True
        )
        assert (log.old_value, log.new_value, log.masked) == (MASK, None, True)

    def test_who_deleted_and_the_correlation_id_are_recorded(self):
        instance = TestModel.objects.create(test_char_field="last")
        pk = instance.pk

        with set_actor(None, remote_addr="10.0.0.1"), set_correlation_id("request-1"):
            instance.delete()

        log = FieldLog.objects.get(instance_id=pk, deleted=True)
        assert (log.remote_addr, log.correlation_id) == ("10.0.0.1", "request-1")

    def test_callbacks_receive_the_deletion_logs(self):
        seen = []

        def callback(instance, fields, logs):
            seen.append(
                {
                    name: (log.old_value, log.new_value, log.deleted)
                    for name, log in logs.items()
                }
            )

        set_config({"callbacks": [callback]}, "testmodel")
        instance = TestModel.objects.create(test_char_field="last")
        seen.clear()
        instance.delete()

        assert seen == [{"test_char_field": ("last", None, True)}]

    def test_callbacks_do_not_run_without_logs(self):
        seen = []
        set_config({"callbacks": [lambda *args: seen.append(args)]}, "testmodel")
        instance = TestModel.objects.create()
        seen.clear()
        instance.delete()

        assert seen == []

    def test_the_instance_of_a_deletion_log_does_not_exist(self):
        instance = TestModel.objects.create(test_char_field="last")
        pk = instance.pk
        instance.delete()

        log = FieldLog.objects.get(instance_id=pk, deleted=True)
        with pytest.raises(TestModel.DoesNotExist):
            log.instance  # noqa: B018


@pytest.mark.django_db(transaction=True, databases=["default", "other"])
@pytest.mark.usefixtures("deletions_logged")
def test_deletions_on_a_secondary_database_are_logged():
    """The stored row is read from the database the instance is deleted
    from."""
    instance = TestModel(test_char_field="last")
    instance.save(using="other")
    pk = instance.pk
    instance.delete()

    assert deletion_logs(TestModel, pk) == {"test_char_field": ("last", None)}


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("restore_settings")
class TestLogDeletionsOption:
    def test_off_by_default(self):
        instance = TestModel.objects.create(test_char_field="last")
        pk = instance.pk
        instance.delete()

        assert deletion_logs(TestModel, pk) == {}
        # Django keeps fast-deleting the model's rows.
        assert not pre_delete.has_listeners(TestModel)
        assert not post_delete.has_listeners(TestModel)

    @pytest.mark.parametrize("scope", ["global", "testapp", "testmodel"])
    def test_any_scope_turns_it_on(self, scope):
        set_config({"log_deletions": True}, scope)
        instance = TestModel.objects.create(test_char_field="last")
        pk = instance.pk
        instance.delete()

        assert deletion_logs(TestModel, pk) == {"test_char_field": ("last", None)}

    @pytest.mark.parametrize(
        ("scopes", "logged"),
        [
            ({"global": True, "testmodel": False}, False),
            ({"testapp": True, "testmodel": False}, False),
            ({"global": False, "testapp": True}, True),
        ],
    )
    def test_the_most_specific_scope_applies(self, scopes, logged):
        for scope, value in scopes.items():
            set_config({"log_deletions": value}, scope)
        instance = TestModel.objects.create(test_char_field="last")
        pk = instance.pk
        instance.delete()

        assert bool(deletion_logs(TestModel, pk)) == logged

    def test_receivers_are_disconnected_when_turned_off(self):
        set_config({"log_deletions": True}, "testmodel")
        assert pre_delete.has_listeners(TestModel)
        assert post_delete.has_listeners(TestModel)

        set_config({"log_deletions": False}, "testmodel")
        assert not pre_delete.has_listeners(TestModel)
        assert not post_delete.has_listeners(TestModel)

    def test_receivers_recheck_the_configuration(self):
        """A receiver still connected does nothing for a model that no
        longer logs deletions."""
        instance = TestModel.objects.create(test_char_field="last")

        signals.pre_delete_log_fields(TestModel, instance)

        assert not hasattr(instance, PRE_DELETE_ATTR)

    def test_direct_calls_ignore_models_that_do_not_log_them(self):
        instance = TestModel.objects.create(test_char_field="last")
        setattr(instance, PRE_DELETE_ATTR, instance)

        assert log_deletions(TestModel, [instance]) == {}
