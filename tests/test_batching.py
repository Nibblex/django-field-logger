"""Lookups with many primary keys are split to fit the backend's limit on
query parameters (999 on SQLite before 3.32); a single huge ``IN`` made
the user's own operation fail."""

import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from fieldlogger import db
from fieldlogger.models import FieldLog

from .testapp.models import TestModel, TestModelRelated2

M2M_ONLY = {
    "LOGGING_APPS": {
        "testapp": {"models": {"TestModel": {"fields": ["test_many_to_many_field"]}}}
    }
}


def relate_all(instances, related):
    through = TestModel.test_many_to_many_field.through
    through.objects.bulk_create(
        [
            through(testmodel_id=instance.pk, testmodelrelated2_id=related.pk)
            for instance in instances
        ],
        batch_size=1000,
    )


def largest_in_list(queries):
    """Size of the longest ``IN (...)`` list among the captured queries."""
    sizes = [
        match.group(1).count(",") + 1
        for query in queries
        for match in re.finditer(r"\bIN \(([^()]*)\)", query["sql"])
    ]
    return max(sizes, default=0)


@pytest.fixture
def batch_size_2(monkeypatch):
    """Simulate a backend that accepts 2 parameters per query, so every
    batched lookup takes several queries. Django's own in_bulk() batches
    by max_query_params before 6.1 and by bulk_batch_size since."""
    monkeypatch.setattr(type(connection.features), "max_query_params", 2)
    monkeypatch.setattr(
        type(connection.ops), "bulk_batch_size", lambda self, fields, objs: 2
    )


def test_batches_split_values_by_backend_size(batch_size_2):
    fields = [TestModel._meta.pk]
    assert list(db.batches([1, 2, 3, 4, 5], fields)) == [[1, 2], [3, 4], [5]]
    assert list(db.batches([], fields)) == []


def test_batches_pass_every_field_to_the_backend(monkeypatch):
    """Each value takes one parameter per field, so the backend divides its
    limit by the number of fields."""
    received = []

    def bulk_batch_size(self, fields, objs):
        received.append(fields)
        return 999 // len(fields)

    monkeypatch.setattr(type(connection.ops), "bulk_batch_size", bulk_batch_size)
    fields = [TestModel._meta.pk, TestModel._meta.get_field("test_unique_field")]

    chunks = list(db.batches(list(range(1000)), fields))

    assert received == [fields]
    assert [len(chunk) for chunk in chunks] == [499, 499, 2]


def test_batches_max_size_caps_the_backend_size(batch_size_2):
    fields = [TestModel._meta.pk]
    assert list(db.batches([1, 2, 3], fields, max_size=1)) == [[1], [2], [3]]
    # A cap above the backend size leaves it unchanged.
    assert list(db.batches([1, 2, 3], fields, max_size=10)) == [[1, 2], [3]]


@pytest.mark.django_db(transaction=True)
def test_reverse_clear_in_batches_logs_every_instance(batch_size_2):
    """Covers m2m_pks and the callbacks' instance lookup, with callbacks."""
    shared = TestModelRelated2.objects.create()
    instances = [TestModel.objects.create() for _ in range(5)]
    relate_all(instances, shared)

    with CaptureQueriesContext(connection) as queries:
        shared.test_reverse_m2m.clear()

    assert largest_in_list(queries) == 2
    logs = FieldLog.objects.filter(field="test_many_to_many_field", created=False)
    assert sorted(logs.values_list("new_value", flat=True)) == [[]] * 5
    # The default test settings add callbacks that mark every log.
    assert all(log.extra_data for log in logs)


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("supports_ignore_conflicts", "batch_size_2")
def test_bulk_create_ignore_conflicts_in_batches():
    existing = TestModel.objects.create(test_unique_field="dup")

    objs = [TestModel(test_unique_field=f"u{i}") for i in range(4)]
    objs.append(TestModel(test_unique_field="dup"))
    with CaptureQueriesContext(connection) as queries:
        TestModel.objects.bulk_create(objs, ignore_conflicts=True)

    assert largest_in_list(queries) == 2
    logged = set(
        # Excluded by instance: comparing JSON values to strings is not
        # portable (it fails on MariaDB with Django 4.2).
        FieldLog.objects.filter(field="test_unique_field", created=True)
        .exclude(instance_id=str(existing.pk))
        .values_list("new_value", flat=True)
    )
    assert logged == {f"u{i}" for i in range(4)}


@pytest.mark.django_db(transaction=True)
def test_reverse_clear_beyond_the_parameter_limit(settings):
    """With the real backend limit: one more instance than parameters a
    query accepts."""
    limit = connection.features.max_query_params
    if limit is None or limit > 40_000:
        # Oracle's 65535 would take minutes to exceed; the batch_size_2
        # tests cover the batching itself on every backend.
        pytest.skip("Database has no low limit on query parameters")
    settings.FIELD_LOGGER_SETTINGS = M2M_ONLY
    shared = TestModelRelated2.objects.create()
    instances = TestModel.objects.bulk_create(
        [TestModel() for _ in range(limit + 1)], log_fields=False
    )
    relate_all(instances, shared)

    shared.test_reverse_m2m.clear()

    assert FieldLog.objects.filter(field="test_many_to_many_field").count() == (
        limit + 1
    )
