"""FieldLoggerMixin.fieldlog_set: always the current logs of the instance."""

import pytest

from fieldlogger.models import FieldLog

from .testapp.models import TestModel


def logs_in_db(instance):
    return FieldLog.objects.filter(
        app_label="testapp", model_name="testmodel", instance_id=instance.pk
    ).count()


@pytest.mark.django_db(transaction=True)
class TestFieldLogSet:
    def test_includes_logs_created_after_it_was_evaluated(self):
        instance = TestModel.objects.create(test_char_field="old")
        assert len(list(instance.fieldlog_set)) == 1

        instance.test_char_field = "new"
        instance.save()

        assert len(list(instance.fieldlog_set)) == 2
        assert instance.fieldlog_set.count() == logs_in_db(instance) == 2

    def test_uses_the_primary_key_of_each_access(self):
        """Accessed before the instance is saved, it has no primary key."""
        instance = TestModel(test_char_field="new")
        assert not instance.fieldlog_set.exists()

        instance.save()

        assert instance.fieldlog_set.count() == logs_in_db(instance) == 1
