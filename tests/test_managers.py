import django
import pytest
from asgiref.sync import async_to_sync
from django.db import connections

from fieldlogger.config import get_config
from fieldlogger.fieldlogger import PRE_INSTANCE_ATTR
from fieldlogger.managers import MAX_OR_TERMS, existing_rows, log_upserted
from fieldlogger.models import FieldLog

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


def upsert_unique_fields(unique_fields):
    """``unique_fields`` argument for ``bulk_create(update_conflicts=True)``:
    MySQL and MariaDB upsert on any unique constraint and reject it."""
    features = connections["default"].features
    if features.supports_update_conflicts_with_target:
        return {"unique_fields": unique_fields}
    return {}


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


@pytest.mark.skipif(
    django.VERSION < (4, 1), reason="update_conflicts requires Django 4.1"
)
@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("supports_update_conflicts")
class TestBulkCreateUpdateConflicts:
    def upsert(self, objs, manager=TestModel.objects, **kwargs):
        return manager.bulk_create(
            objs,
            update_conflicts=True,
            update_fields=["test_char_field"],
            **upsert_unique_fields(["test_unique_field"]),
            **kwargs,
        )

    def test_updated_rows_are_logged_as_changes(self):
        existing = TestModel.objects.create(
            test_unique_field="dup", test_char_field="old", test_integer_field=1
        )

        # test_integer_field is not in update_fields, so it is not written
        # and must not be logged.
        updating = TestModel(
            test_unique_field="dup", test_char_field="new", test_integer_field=2
        )
        self.upsert([updating])

        assert updating.pk == existing.pk
        update_logs = existing.fieldlog_set.filter(created=False)
        log = update_logs.get()
        assert (log.field, log.old_value, log.new_value) == (
            "test_char_field",
            "old",
            "new",
        )

    def test_inserted_rows_are_logged_as_creations(self):
        TestModel.objects.create(test_unique_field="dup")

        inserted = TestModel(test_unique_field="other", test_char_field="new")
        self.upsert([TestModel(test_unique_field="dup"), inserted])

        assert inserted.pk is not None
        assert char_logs(inserted, created=True).get().new_value == "new"

    def test_large_upsert_is_logged(self):
        count = MAX_OR_TERMS * 3
        TestModel.objects.bulk_create(
            [TestModel(test_unique_field=str(i)) for i in range(count)],
            log_fields=False,
        )

        objs = [
            TestModel(test_unique_field=str(i), test_char_field="new")
            for i in range(count)
        ]
        self.upsert(objs, run_callbacks=False)

        assert FieldLog.objects.filter(created=False).count() == count
        assert not FieldLog.objects.filter(created=True).exists()

    @pytest.mark.django_db(transaction=True, databases=["default", "other"])
    def test_upsert_on_secondary_database_is_logged(self):
        existing = TestModel.objects.using("other").create(
            test_unique_field="dup", test_char_field="old"
        )

        self.upsert(
            [TestModel(test_unique_field="dup", test_char_field="new")],
            manager=TestModel.objects.using("other"),
        )

        log = char_logs(existing, created=False).get()
        assert (log.old_value, log.new_value) == ("old", "new")

    def test_inserts_after_an_upsert_get_new_keys(self):
        """Django < 5.0 leaves the keys of inserted rows unset, so they are
        assigned manually; the sequence must follow them."""
        TestModel.objects.create(test_unique_field="existing")

        (inserted,) = self.upsert([TestModel(test_unique_field="new")])
        created = TestModel.objects.create(test_char_field="single")

        assert created.pk > inserted.pk

    def test_without_logging_primary_keys_are_left_to_django(self):
        """Assigning a primary key to an object that updates an existing
        row would give it a pk that is not its row's."""
        existing = TestModel.objects.create(test_unique_field="dup")
        log_count = existing.fieldlog_set.count()

        updating = TestModel(test_unique_field="dup", test_char_field="new")
        self.upsert([updating], log_fields=False)

        assert updating.pk in (None, existing.pk)
        assert existing.fieldlog_set.count() == log_count


@pytest.mark.django_db(transaction=True)
class TestExistingRows:
    def logging_fields(self):
        return get_config()[TestModel]["logging_fields"]

    def test_matches_on_unique_fields(self):
        existing = TestModel.objects.create(test_unique_field="dup")
        objs = [TestModel(test_unique_field="new"), TestModel(test_unique_field="dup")]

        rows = existing_rows(
            TestModel, objs, ["test_unique_field"], self.logging_fields(), None
        )

        assert rows == {1: existing}

    def test_matches_on_every_unique_field_together(self):
        existing = TestModel.objects.create(test_unique_field="dup")
        objs = [
            TestModel(pk=existing.pk, test_unique_field="other"),
            TestModel(pk=existing.pk, test_unique_field="dup"),
        ]

        rows = existing_rows(
            TestModel, objs, ["pk", "test_unique_field"], self.logging_fields(), None
        )

        assert rows == {1: existing}

    def test_without_unique_fields_matches_on_any_unique_field(self):
        """MySQL upserts on any unique constraint, so unique_fields is not
        given there."""
        by_pk = TestModel.objects.create(test_unique_field="a")
        by_unique = TestModel.objects.create(test_unique_field="b")
        objs = [
            TestModel(pk=by_pk.pk),
            TestModel(test_unique_field="b"),
            TestModel(test_unique_field="new"),
        ]

        rows = existing_rows(TestModel, objs, None, self.logging_fields(), None)

        assert rows == {0: by_pk, 1: by_unique}

    def test_without_unique_fields_uses_a_single_query(self, django_assert_num_queries):
        TestModel.objects.create(test_unique_field="b")
        objs = [TestModel(pk=1), TestModel(test_unique_field="b")]

        with django_assert_num_queries(1):
            existing_rows(TestModel, objs, None, self.logging_fields(), None)

    @pytest.mark.parametrize(
        "unique_fields",
        [["test_unique_field"], ["pk", "test_unique_field"]],
        ids=["single-field", "multi-field"],
    )
    def test_large_batches(self, unique_fields):
        """More objects than fit in one query (SQLite limits both the
        parameters and the expression depth) are matched in batches."""
        count = MAX_OR_TERMS * 3
        rows = TestModel.objects.bulk_create(
            [TestModel(test_unique_field=str(i)) for i in range(count)],
            log_fields=False,
        )
        objs = [
            TestModel(pk=row.pk, test_unique_field=str(i)) for i, row in enumerate(rows)
        ]
        objs.append(TestModel(pk=count + 1, test_unique_field="new"))

        matched = existing_rows(
            TestModel, objs, unique_fields, self.logging_fields(), None
        )

        assert {index: row.pk for index, row in matched.items()} == {
            index: row.pk for index, row in enumerate(rows)
        }

    def test_null_values_never_match(self):
        TestModel.objects.create(test_unique_field=None)

        rows = existing_rows(
            TestModel,
            [TestModel(test_unique_field=None)],
            ["test_unique_field"],
            self.logging_fields(),
            None,
        )

        assert rows == {}

    def test_fetches_logged_fields_only(self):
        TestModel.objects.create(test_unique_field="dup", test_char_field="old")

        (row,) = existing_rows(
            TestModel,
            [TestModel(test_unique_field="dup")],
            ["test_unique_field"],
            self.logging_fields(),
            None,
        ).values()

        assert row.test_char_field == "old"
        assert row.get_deferred_fields() == {
            field.attname
            for field in TestModel._meta.concrete_fields
            if field not in self.logging_fields()
            and field.name not in ("id", "test_unique_field")
        }


@pytest.mark.django_db(transaction=True)
def test_log_upserted_logs_update_fields_only():
    existing = TestModel.objects.create(test_char_field="old", test_integer_field=1)
    row = TestModel._base_manager.get(pk=existing.pk)
    obj = TestModel(test_char_field="new", test_integer_field=2)
    # What the upsert writes: only update_fields. The logged values are read
    # back from the database, so test_integer_field must not be logged.
    TestModel.objects.filter(pk=existing.pk).update(test_char_field="new")

    log_upserted(TestModel, [(obj, row)], ["test_char_field"], run_callbacks=False)

    assert obj.pk == existing.pk
    assert not hasattr(obj, PRE_INSTANCE_ATTR)
    log = existing.fieldlog_set.get(created=False)
    assert (log.field, log.old_value, log.new_value) == (
        "test_char_field",
        "old",
        "new",
    )
