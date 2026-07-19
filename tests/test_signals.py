import pytest

from fieldlogger import signals
from fieldlogger.models import FieldLog

from .helpers import CREATE_FORM
from .testapp.models import TestModel


@pytest.mark.django_db(transaction=True)
def test_raw_saves_are_not_logged():
    """Fixture loading (raw saves) must not stash state nor create logs."""
    instance = TestModel.objects.create(**CREATE_FORM)
    log_count = FieldLog.objects.count()

    signals.pre_save_log_fields(TestModel, instance, raw=True)
    assert not hasattr(instance, "_fieldlogger_pre_instance")

    signals.post_save_log_fields(
        TestModel, instance, created=False, update_fields=None, raw=True
    )
    assert FieldLog.objects.count() == log_count


@pytest.mark.django_db(transaction=True, databases=["default", "other"])
def test_save_on_secondary_database_is_logged():
    """The pre-save state is fetched from the database being written to."""
    instance = TestModel(test_char_field="first")
    instance.save(using="other")

    log = instance.fieldlog_set.get(field="test_char_field")
    assert log.created and log.new_value == "first"

    instance.test_char_field = "second"
    instance.save(using="other")

    update_logs = instance.fieldlog_set.filter(field="test_char_field", created=False)
    assert update_logs.count() == 1
    assert update_logs.get().old_value == "first"
