import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from fieldlogger import fieldlogger
from fieldlogger.models import FieldLog

from .testapp.models import TestModel, TestModelRelated


@pytest.mark.django_db(transaction=True)
def test_log_fields_on_unconfigured_model():
    instance = TestModelRelated.objects.create()
    assert fieldlogger.log_fields(TestModelRelated, [instance]) == {}
    assert instance.fieldlog_set.count() == 0


@pytest.mark.django_db(transaction=True)
def test_log_fields_returns_logs_keyed_by_pk_and_field_name():
    instance = TestModel.objects.create(test_char_field="test")

    logs = fieldlogger.log_fields(TestModel, [instance], run_callbacks=False)

    assert set(logs) == {instance.pk}
    assert logs[instance.pk]["test_char_field"].new_value == "test"


@pytest.mark.django_db(transaction=True)
def test_log_fields_without_logged_fields_queries_nothing(django_assert_num_queries):
    instance = TestModel.objects.create(test_char_field="x")

    with django_assert_num_queries(0):
        logs = fieldlogger.log_fields(
            TestModel, [instance], update_fields=["not_logged"], run_callbacks=False
        )

    assert logs == {}


@pytest.mark.django_db(transaction=True)
def test_log_fields_skips_instances_missing_from_the_database():
    instance = TestModel.objects.create(test_char_field="x")
    TestModel.objects.filter(pk=instance.pk).delete()

    assert fieldlogger.log_fields(TestModel, [instance], run_callbacks=False) == {}


@pytest.mark.django_db(transaction=True)
class TestLogsWithoutPkReturningSupport:
    """Callbacks receive saved logs even where bulk_create cannot return
    primary keys: they may save them or follow previous_log."""

    @pytest.fixture(autouse=True)
    def callback(self, no_returning_pks, settings):
        self.received = []

        def callback(instance, logging_fields, logs):
            for log in logs.values():
                self.received.append(log.pk)
                log.previous_log  # noqa: B018 - must not fail
                log.extra_data["seen"] = True
                log.save()

        settings.FIELD_LOGGER_SETTINGS = {
            "FAIL_SILENTLY": False,
            "LOGGING_APPS": {
                "testapp": {
                    "callbacks": [callback],
                    "models": {"TestModel": {"fields": ["test_char_field"]}},
                }
            },
        }

    def test_logs_have_primary_keys(self):
        instance = TestModel.objects.create(test_char_field="a")
        instance.test_char_field = "b"
        instance.save()

        assert None not in self.received
        assert sorted(self.received) == list(
            FieldLog.objects.order_by("pk").values_list("pk", flat=True)
        )

    def test_saving_a_log_in_a_callback_does_not_duplicate_it(self):
        instance = TestModel.objects.create(test_char_field="a")

        log = instance.fieldlog_set.get()
        assert log.extra_data == {"seen": True}


@pytest.mark.django_db(transaction=True)
def test_logs_without_pk_returning_support_keep_the_sequence(no_returning_pks):
    """Logs get their keys from the database, so later inserts of logs do
    not reuse them (explicit keys do not advance PostgreSQL sequences)."""
    log = {"app_label": "testapp", "model_name": "testmodel", "field": "f"}
    FieldLog.objects.create(instance_id="1", **log)

    TestModel.objects.create(test_char_field="a")
    created = FieldLog.objects.create(instance_id="2", **log)

    assert created.pk == max(FieldLog.objects.values_list("pk", flat=True))


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("returning", [True, False])
def test_save_logs_sets_primary_keys(monkeypatch, returning):
    """One INSERT where the backend returns keys, one per log otherwise.
    Patched directly so both paths run on every Django version (SQLite
    only returns keys from Django 4.0)."""
    monkeypatch.setattr(fieldlogger, "db_supports_returning_pks", lambda *a: returning)
    logs = [
        FieldLog(app_label="testapp", model_name="testmodel", field="f", instance_id=i)
        for i in range(3)
    ]

    with CaptureQueriesContext(connection) as queries:
        fieldlogger._save_logs(logs)

    inserts = [q for q in queries if q["sql"].startswith("INSERT")]
    assert len(inserts) == (1 if returning else 3)
    assert FieldLog.objects.count() == 3
    if not returning:
        # With returning, the keys are set by Django's bulk_create, which
        # the real backend (not the patched check) decides.
        assert sorted(log.pk for log in logs) == sorted(
            FieldLog.objects.values_list("pk", flat=True)
        )
