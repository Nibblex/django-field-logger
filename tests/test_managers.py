import pytest
from asgiref.sync import async_to_sync

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


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("supports_ignore_conflicts")
class TestIgnoreConflictsPrimaryKeys:
    """Objects not inserted because of a conflict must not keep a primary
    key that no row has: saving them would insert with that key, which on
    PostgreSQL and Oracle does not advance the sequence."""

    def test_conflicting_objects_get_no_primary_key(self):
        TestModel.objects.create(test_unique_field="dup")

        conflicting = TestModel(test_unique_field="dup")
        inserted = TestModel(test_unique_field="new")
        TestModel.objects.bulk_create([conflicting, inserted], ignore_conflicts=True)

        assert conflicting.pk is None
        assert TestModel.objects.filter(pk=inserted.pk).exists()

    def test_preset_primary_keys_are_kept(self):
        existing = TestModel.objects.create(test_unique_field="dup")

        conflicting = TestModel(pk=existing.pk, test_unique_field="other")
        TestModel.objects.bulk_create([conflicting], ignore_conflicts=True)

        assert conflicting.pk == existing.pk

    def test_keys_are_cleared_without_logging_too(self):
        """Keys are still assigned with log_fields=False (callers rely on
        them), so they are cleared there as well."""
        TestModel.objects.create(test_unique_field="dup")

        conflicting = TestModel(test_unique_field="dup")
        inserted = TestModel(test_unique_field="new")
        TestModel.objects.bulk_create(
            [conflicting, inserted], ignore_conflicts=True, log_fields=False
        )

        assert conflicting.pk is None
        assert TestModel.objects.filter(pk=inserted.pk).exists()

    def test_saving_a_conflicting_object_later_creates_a_new_row(self):
        TestModel.objects.create(test_unique_field="dup")
        conflicting = TestModel(test_unique_field="dup")
        TestModel.objects.bulk_create([conflicting], ignore_conflicts=True)

        conflicting.test_unique_field = "renamed"
        conflicting.save()
        created = TestModel.objects.create(test_char_field="next")

        assert conflicting.pk is not None
        assert created.pk > conflicting.pk


def char_logs(instance, created):
    return instance.fieldlog_set.filter(field="test_char_field", created=created)


@pytest.mark.django_db(transaction=True, databases=["default", "other"])
@pytest.mark.parametrize(
    "queryset",
    [
        lambda: TestModel.objects.all(),
        lambda: TestModel.objects.filter(pk__gt=0),
        lambda: TestModel.objects.using("other"),
    ],
    ids=["all", "filter", "using"],
)
class TestBulkOperationsOnQuerysets:
    """Logging must not depend on calling the bulk methods on the manager
    itself: chained calls return a QuerySet."""

    def test_bulk_create_is_logged(self, queryset):
        (instance,) = queryset().bulk_create([TestModel(test_char_field="new")])

        assert char_logs(instance, created=True).get().new_value == "new"

    def test_bulk_update_is_logged(self, queryset):
        (instance,) = queryset().bulk_create([TestModel(test_char_field="old")])
        instance.test_char_field = "new"

        queryset().bulk_update([instance], ["test_char_field"])

        log = char_logs(instance, created=False).get()
        assert (log.old_value, log.new_value) == ("old", "new")


@pytest.mark.django_db(transaction=True)
class TestAsyncBulkOperations:
    # Called on a QuerySet: the manager only exposes the async methods on
    # Django >= 4.1, the QuerySet on every version.

    def test_abulk_create_is_logged(self):
        (instance,) = async_to_sync(TestModel.objects.all().abulk_create)(
            [TestModel(test_char_field="new")]
        )

        assert char_logs(instance, created=True).count() == 1

    def test_abulk_update_is_logged(self):
        instance = TestModel.objects.create(test_char_field="old")
        instance.test_char_field = "new"

        async_to_sync(TestModel.objects.all().abulk_update)(
            [instance], ["test_char_field"]
        )

        assert char_logs(instance, created=False).count() == 1

    def test_async_methods_accept_log_fields(self):
        (instance,) = async_to_sync(TestModel.objects.all().abulk_create)(
            [TestModel(test_char_field="old")], log_fields=False
        )
        instance.test_char_field = "new"
        async_to_sync(TestModel.objects.all().abulk_update)(
            [instance], ["test_char_field"], log_fields=False
        )

        assert not instance.fieldlog_set.exists()
