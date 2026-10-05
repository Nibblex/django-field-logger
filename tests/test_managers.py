import pytest

from .testapp.models import TestModel


@pytest.mark.django_db(transaction=True)
def test_bulk_create_ignore_conflicts_skips_conflicting_rows():
    """Rows not inserted because of a conflict must not be logged."""
    TestModel.objects.create(test_unique_field="dup")

    conflicting = TestModel(test_unique_field="dup")
    inserted = TestModel(test_char_field="ok")
    TestModel.objects.bulk_create([conflicting, inserted], ignore_conflicts=True)

    assert inserted.fieldlog_set.count() == 1
    assert conflicting.fieldlog_set.count() == 0


@pytest.mark.django_db(transaction=True)
def test_bulk_create_accepts_a_generator():
    """A single-use iterable must be both inserted and logged."""
    instances = TestModel.objects.bulk_create(
        TestModel(test_char_field=str(i)) for i in range(2)
    )

    assert TestModel.objects.count() == 2
    for instance in instances:
        assert instance.fieldlog_set.filter(field="test_char_field").count() == 1


@pytest.mark.django_db(transaction=True)
def test_bulk_update_accepts_a_generator():
    """A single-use iterable must be both updated and logged."""
    instance = TestModel.objects.create(test_char_field="old")
    instance.test_char_field = "new"

    TestModel.objects.bulk_update((obj for obj in [instance]), ["test_char_field"])

    instance.refresh_from_db()
    assert instance.test_char_field == "new"
    assert instance.fieldlog_set.filter(created=False).count() == 1
