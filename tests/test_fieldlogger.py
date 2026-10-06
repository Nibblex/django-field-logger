import pytest

from fieldlogger import fieldlogger, managers

from .helpers import CREATE_FORM, bulk_check_logs
from .testapp.models import SoftDeleteModel, TestModel, TestModelRelated


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
def test_bulk_create_ignore_conflicts_with_filtering_default_manager():
    """A new row must not get the pk of a hidden row; with
    ``ignore_conflicts`` that collision would silently drop it."""
    # The hidden row holds the highest pk, so a max computed over the
    # visible rows alone would reuse it.
    SoftDeleteModel.items.create()
    SoftDeleteModel.items.create(deleted=True)

    SoftDeleteModel.items.bulk_create([SoftDeleteModel()], ignore_conflicts=True)

    assert SoftDeleteModel._base_manager.count() == 3


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


def test_failing_callback_is_logged_when_fail_silently(caplog):
    def bad_callback(*args):
        raise ValueError("boom")

    fieldlogger._run_callbacks(
        [TestModel()], [bad_callback], {}, frozenset(), fail_silently=True
    )

    assert "bad_callback" in caplog.text


@pytest.mark.django_db(transaction=True)
def test_bulk_create_logs_without_pk_returning_support(monkeypatch):
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
