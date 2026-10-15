"""FieldLoggerManager combined with a user's own QuerySet keeps logging
bulk operations (they live on FieldLoggerQuerySet)."""

import pytest

from fieldlogger.managers import FieldLoggerManager, FieldLoggerQuerySet
from fieldlogger.models import FieldLog

from .testapp.models import ActiveQuerySet, CustomQuerySetModel

LOGGED = {
    "LOGGING_APPS": {
        "testapp": {"models": {"CustomQuerySetModel": {"fields": ["name"]}}}
    }
}


def name_logs():
    return FieldLog.objects.filter(model_name="customquerysetmodel", field="name")


@pytest.fixture(autouse=True)
def logged(settings):
    settings.FIELD_LOGGER_SETTINGS = LOGGED


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("manager", ["objects", "overridden"])
class TestCustomQuerySets:
    def get(self, manager):
        return getattr(CustomQuerySetModel, manager)

    def test_queryset_has_both_classes(self, manager):
        queryset = self.get(manager).all()
        assert isinstance(queryset, FieldLoggerQuerySet)
        assert isinstance(queryset, ActiveQuerySet)

    def test_custom_methods_are_kept(self, manager):
        CustomQuerySetModel.objects.create(name="a")
        CustomQuerySetModel.objects.create(name="b", deleted=True)

        # A manager overriding get_queryset() does not expose the QuerySet's
        # methods itself (plain Django), so they are reached through it.
        active = self.get(manager).get_queryset().active()
        assert list(active.values_list("name", flat=True)) == ["a"]

    def test_bulk_create_is_logged(self, manager):
        self.get(manager).bulk_create([CustomQuerySetModel(name="new")])

        assert name_logs().filter(created=True).count() == 1

    def test_bulk_update_is_logged(self, manager):
        instance = CustomQuerySetModel.objects.create(name="old")
        instance.name = "new"

        self.get(manager).bulk_update([instance], ["name"])

        assert name_logs().filter(created=False).count() == 1

    def test_chained_bulk_create_is_logged(self, manager):
        self.get(manager).get_queryset().active().bulk_create(
            [CustomQuerySetModel(name="new")]
        )

        assert name_logs().filter(created=True).count() == 1


def test_already_logging_querysets_are_unchanged():
    class Own(FieldLoggerQuerySet):
        pass

    assert FieldLoggerManager.from_queryset(Own)._queryset_class is Own
