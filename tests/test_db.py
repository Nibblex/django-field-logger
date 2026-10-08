from types import SimpleNamespace

import pytest
from django.db import connection

from fieldlogger import db
from fieldlogger.models import FieldLog

from .testapp.models import SoftDeleteModel, TestModel

HAS_SEQUENCES = ("postgresql", "oracle")


@pytest.mark.django_db
def test_db_supports_returning_pks_follows_the_backend(no_returning_pks):
    assert db.db_supports_returning_pks(FieldLog) is False


@pytest.mark.django_db(transaction=True)
def test_reserve_primary_keys_assigns_sequential_pks():
    """MAX(pk) + n on backends without named sequences."""
    if connection.vendor in HAS_SEQUENCES:
        pytest.skip("Keys come from the sequence there")
    logs = [
        FieldLog(app_label="testapp", model_name="testmodel", field="f", instance_id=i)
        for i in range(3)
    ]

    db.reserve_primary_keys(logs, FieldLog)
    max_pk = FieldLog.objects.count()
    assert [log.pk for log in logs] == [max_pk + 1, max_pk + 2, max_pk + 3]


@pytest.mark.django_db(transaction=True)
def test_reserve_primary_keys_keeps_preset_pks():
    logs = [
        FieldLog(app_label="testapp", model_name="testmodel", field="f"),
        FieldLog(app_label="testapp", model_name="testmodel", field="f", pk=999),
    ]

    db.reserve_primary_keys(logs, FieldLog)
    assert logs[0].pk is not None
    assert logs[1].pk == 999


@pytest.mark.django_db(transaction=True)
def test_reserve_primary_keys_counts_rows_hidden_by_default_manager():
    """The next pk is computed over every row, including those that the
    model's default manager filters out, and works on models without an
    ``objects`` manager."""
    SoftDeleteModel.items.create()
    hidden = SoftDeleteModel.items.create(deleted=True)
    assert SoftDeleteModel.items.count() == 1

    objs = [SoftDeleteModel()]
    db.reserve_primary_keys(objs, SoftDeleteModel)
    assert objs[0].pk == hidden.pk + 1


def fake_connection(vendor):
    return SimpleNamespace(
        vendor=vendor, ops=SimpleNamespace(quote_name=lambda name: f'"{name}"')
    )


def test_nextval_sql_per_backend():
    assert db._nextval_sql(fake_connection("postgresql"), "seq", 3) == (
        "SELECT nextval(%s) FROM generate_series(1, %s)",
        ['"seq"', 3],
    )
    assert db._nextval_sql(fake_connection("oracle"), "seq", 3) == (
        'SELECT "seq".NEXTVAL FROM DUAL CONNECT BY LEVEL <= %s',
        [3],
    )
    assert db._nextval_sql(fake_connection("sqlite"), "seq", 3) is None


@pytest.mark.django_db(transaction=True)
def test_reserved_keys_are_not_given_to_other_inserts():
    """Keys come from the sequence, so an insert between reserving them and
    the bulk insert (e.g. from another process) cannot take them."""
    if connection.vendor not in HAS_SEQUENCES:
        pytest.skip("Database has no named sequences; keys follow MAX(pk)")
    objs = [TestModel() for _ in range(3)]
    db.reserve_primary_keys(objs, TestModel)

    other = TestModel.objects.create()
    TestModel.objects.bulk_create(objs, log_fields=False)
    later = TestModel.objects.create()

    keys = {obj.pk for obj in objs}
    assert other.pk not in keys
    assert later.pk not in keys and later.pk > max(keys)


@pytest.mark.django_db
def test_without_unsaved_objects_nothing_is_queried(django_assert_num_queries):
    with django_assert_num_queries(0):
        db.reserve_primary_keys([TestModel(pk=1)], TestModel)


@pytest.mark.django_db
class TestReserveFromSequence:
    """The paths that depend on the backend, run on any of them."""

    def patch_sequences(self, monkeypatch, result):
        def get_sequences(cursor, table_name, table_fields=()):
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(connection.introspection, "get_sequences", get_sequences)

    def test_backend_without_sequence_introspection(self, monkeypatch):
        self.patch_sequences(monkeypatch, NotImplementedError())
        assert db._reserve_from_sequence(TestModel, "default", 2) is None

    def test_sequence_of_another_column_is_ignored(self, monkeypatch):
        self.patch_sequences(monkeypatch, [{"name": "seq", "column": "other"}])
        assert db._reserve_from_sequence(TestModel, "default", 2) is None

    def test_named_sequence_on_unknown_backend(self, monkeypatch):
        self.patch_sequences(monkeypatch, [{"name": "seq", "column": "id"}])
        monkeypatch.setattr(db, "_nextval_sql", lambda connection, name, count: None)
        assert db._reserve_from_sequence(TestModel, "default", 2) is None

    def test_reserved_values_are_assigned(self, monkeypatch):
        monkeypatch.setattr(
            db, "_reserve_from_sequence", lambda model, using, count: [41, 42]
        )
        objs = [TestModel(), TestModel(pk=7), TestModel()]

        db.reserve_primary_keys(objs, TestModel)

        assert [obj.pk for obj in objs] == [41, 7, 42]

    def test_values_are_taken_from_the_query(self, monkeypatch):
        self.patch_sequences(monkeypatch, [{"name": "seq", "column": "id"}])
        monkeypatch.setattr(
            db,
            "_nextval_sql",
            lambda connection, name, count: (
                "SELECT 41 + %s UNION ALL SELECT 42 + %s",
                [0, 0],
            ),
        )
        assert sorted(db._reserve_from_sequence(TestModel, "default", 2)) == [41, 42]
