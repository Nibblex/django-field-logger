import pytest

from fieldlogger import fieldlogger, managers
from fieldlogger.models import FieldLog

from .helpers import CREATE_FORM, bulk_check_logs
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
def test_set_primary_keys():
    logs = [
        FieldLog(app_label="testapp", model_name="testmodel", field="f", instance_id=i)
        for i in range(3)
    ]

    fieldlogger.set_primary_keys(logs, FieldLog)
    max_pk = FieldLog.objects.count()
    assert [log.pk for log in logs] == [max_pk + 1, max_pk + 2, max_pk + 3]


@pytest.mark.django_db(transaction=True)
def test_set_primary_keys_respects_preset_pks():
    logs = [
        FieldLog(app_label="testapp", model_name="testmodel", field="f"),
        FieldLog(app_label="testapp", model_name="testmodel", field="f", pk=999),
    ]

    fieldlogger.set_primary_keys(logs, FieldLog)
    assert [log.pk for log in logs] == [1, 999]


@pytest.mark.django_db(transaction=True)
def test_log_fields_skips_unreadable_fields():
    """Fields that cannot be read from the previous state are skipped."""
    instance = TestModel.objects.create(test_char_field="x")
    instance._fieldlogger_pre_instance = object()

    assert fieldlogger.log_fields(TestModel, [instance], run_callbacks=False) == {}


def test_failing_callback_is_logged_when_fail_silently(caplog):
    def bad_callback(*args):
        raise ValueError("boom")

    fieldlogger._run_callbacks(
        [TestModel()], [bad_callback], {}, frozenset(), fail_silently=True
    )

    assert "bad_callback" in caplog.text


@pytest.mark.django_db(transaction=True)
def test_bulk_create_without_pk_returning_support(monkeypatch):
    """On databases that cannot return pks from bulk inserts, pks are
    assigned manually and logging still works."""
    monkeypatch.setattr(
        fieldlogger, "db_supports_returning_pks", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        managers, "db_supports_returning_pks", lambda *args, **kwargs: False
    )

    instances = TestModel.objects.bulk_create(
        [TestModel(**CREATE_FORM) for _ in range(2)]
    )

    assert all(instance.pk for instance in instances)
    bulk_check_logs(instances, len(CREATE_FORM), created=True)
