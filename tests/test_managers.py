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
