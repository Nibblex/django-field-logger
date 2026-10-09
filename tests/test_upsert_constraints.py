"""Upserts conflicting on composite unique constraints are logged as changes
of the existing row, not as creations."""

from types import SimpleNamespace

import django
import pytest
from django.db import connection

from fieldlogger import managers
from fieldlogger.config import get_config
from fieldlogger.managers import existing_rows
from fieldlogger.models import FieldLog

from .test_managers import upsert_unique_fields
from .testapp.models import CompositeUniqueModel

LOGGED = {
    "LOGGING_APPS": {
        "testapp": {"models": {"CompositeUniqueModel": {"fields": ["name"]}}}
    }
}


@pytest.fixture(autouse=True)
def logged(settings):
    settings.FIELD_LOGGER_SETTINGS = LOGGED


def name_logs(**kwargs):
    return FieldLog.objects.filter(
        model_name="compositeuniquemodel", field="name", **kwargs
    )


def logging_fields():
    return get_config()[CompositeUniqueModel]["logging_fields"]


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "existing, unique_fields",
    [
        ({"code": "c", "region": "r"}, ["code", "region"]),
        ({"serial": "s", "batch": "b"}, ["serial", "batch"]),
    ],
    ids=["unique_together", "UniqueConstraint"],
)
class TestCompositeConstraints:
    def test_existing_rows_match_without_unique_fields(self, existing, unique_fields):
        row = CompositeUniqueModel.objects.create(**existing)
        objs = [CompositeUniqueModel(**existing), CompositeUniqueModel(code="new")]

        rows = existing_rows(CompositeUniqueModel, objs, None, logging_fields(), None)

        assert rows == {0: row}

    @pytest.mark.skipif(
        django.VERSION < (4, 1), reason="update_conflicts requires Django 4.1"
    )
    @pytest.mark.usefixtures("supports_update_conflicts")
    def test_upsert_is_logged_as_a_change(self, existing, unique_fields):
        row = CompositeUniqueModel.objects.create(name="old", **existing)

        CompositeUniqueModel.objects.bulk_create(
            [CompositeUniqueModel(name="new", **existing)],
            update_conflicts=True,
            update_fields=["name"],
            **upsert_unique_fields(unique_fields),
        )

        assert CompositeUniqueModel.objects.count() == 1
        # The creation log of the existing row, plus the change.
        assert not name_logs(created=True).exclude(instance_id=str(row.pk)).exists()
        log = name_logs(instance_id=str(row.pk), created=False).get()
        assert (log.old_value, log.new_value) == ("old", "new")


def test_unique_field_sets_dedupe_and_skip_expressions():
    """Duplicated sets are kept once; constraints on expressions (no fields)
    are skipped. Conditional constraints are already excluded by Django's
    total_unique_constraints."""
    fields = {
        "id": SimpleNamespace(name="id", unique=True),
        "a": SimpleNamespace(name="a", unique=True),
        "b": SimpleNamespace(name="b", unique=False),
    }
    meta = SimpleNamespace(
        pk=fields["id"],
        concrete_fields=list(fields.values()),
        unique_together=(("a", "b"),),
        total_unique_constraints=[
            SimpleNamespace(fields=("a", "b")),
            SimpleNamespace(fields=()),
        ],
        get_field=fields.__getitem__,
    )

    sets = managers._unique_field_sets(SimpleNamespace(_meta=meta))

    assert sets == [(fields["id"],), (fields["a"],), (fields["a"], fields["b"])]


@pytest.mark.django_db
def test_empty_values_never_conflict_where_stored_as_null(monkeypatch):
    """Oracle stores empty strings as NULL, which never conflict, while
    Django holds them as empty strings on the objects."""
    monkeypatch.setattr(
        type(connection.features), "interprets_empty_strings_as_nulls", True
    )
    CompositeUniqueModel.objects.create(code="c", region="", serial="s", batch="")

    objs = [CompositeUniqueModel(code="c", region="", serial="s", batch="")]

    assert existing_rows(CompositeUniqueModel, objs, None, logging_fields(), None) == {}


def test_can_conflict():
    assert managers._can_conflict(("a", 1), empty_is_null=False)
    assert not managers._can_conflict(("a", None), empty_is_null=False)
    assert managers._can_conflict(("a", ""), empty_is_null=False)
    assert not managers._can_conflict(("a", ""), empty_is_null=True)
    assert not managers._can_conflict((b"",), empty_is_null=True)
