import pytest

from .helpers import CREATE_FORM, bulk_check_logs
from .testapp.models import SoftDeleteModel, TestModel


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("supports_ignore_conflicts")
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


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("supports_ignore_conflicts")
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
def test_bulk_create_logs_without_pk_returning_support(no_returning_pks):
    """Django leaves the keys unset, so they are assigned manually and the
    logs reference the right instances."""
    instances = TestModel.objects.bulk_create(
        [TestModel(**CREATE_FORM) for _ in range(2)]
    )

    assert all(instance.pk for instance in instances)
    bulk_check_logs(instances, len(CREATE_FORM), created=True)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "kwargs, returning",
    [({"ignore_conflicts": True}, True), ({}, False)],
    ids=["ignore_conflicts", "no-returning-pks"],
)
def test_inserts_after_manual_primary_keys_get_new_keys(kwargs, returning, request):
    """Explicit keys do not advance the sequence on PostgreSQL and Oracle;
    without resetting it, the next insert reused them."""
    request.getfixturevalue(
        "supports_ignore_conflicts" if returning else "no_returning_pks"
    )
    # Brings the table's highest key level with its sequence, which the
    # rows of earlier tests may have left ahead.
    TestModel.objects.create(test_char_field="existing")

    (bulk_created,) = TestModel.objects.bulk_create(
        [TestModel(test_char_field="bulk")], **kwargs
    )
    created = TestModel.objects.create(test_char_field="single")

    assert created.pk > bulk_created.pk
