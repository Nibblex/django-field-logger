"""disable_logging(): automatic logging is off inside the block."""

import threading

import pytest
from asgiref.sync import async_to_sync
from django.db import connection
from django.test.utils import CaptureQueriesContext

from fieldlogger import disable_logging, fieldlogger
from fieldlogger.context import logging_disabled
from fieldlogger.models import FieldLog

from .testapp.models import TestModel, TestModelRelated2


def char_logs(instance):
    return instance.fieldlog_set.filter(field="test_char_field").order_by("pk")


def logging_queries(queries):
    """The captured queries that read or insert rows, as logging does."""
    return [q["sql"] for q in queries if q["sql"].startswith(("SELECT", "INSERT"))]


@pytest.mark.django_db(transaction=True)
class TestDisableLogging:
    def test_saves_are_not_logged(self):
        with disable_logging():
            instance = TestModel.objects.create(test_char_field="old")
            instance.test_char_field = "new"
            instance.save()

        assert not FieldLog.objects.exists()

    def test_save_runs_only_its_update(self):
        """The previous and stored values are not read either."""
        instance = TestModel.objects.create(test_char_field="old")
        instance.test_char_field = "new"

        with disable_logging(), CaptureQueriesContext(connection) as queries:
            instance.save()

        assert [q["sql"].split()[0] for q in queries] == ["UPDATE"]

    def test_logging_resumes_after_the_block(self):
        instance = TestModel.objects.create(test_char_field="old")
        with disable_logging():
            instance.test_char_field = "inside"
            instance.save()

        instance.test_char_field = "after"
        instance.save()

        log = char_logs(instance).filter(created=False).get()
        assert (log.old_value, log.new_value) == ("inside", "after")

    def test_m2m_changes_are_not_logged(self):
        instance = TestModel.objects.create()
        related = TestModelRelated2.objects.create()

        with disable_logging():
            instance.test_many_to_many_field.add(related)
            instance.test_many_to_many_field.set([])
            related.test_reverse_m2m.add(instance)
            related.test_reverse_m2m.clear()

        assert not instance.fieldlog_set.filter(
            field="test_many_to_many_field"
        ).exists()

    def test_bulk_operations_are_not_logged(self):
        with disable_logging():
            objs = TestModel.objects.bulk_create([TestModel(test_char_field="old")])
            objs[0].test_char_field = "new"
            with CaptureQueriesContext(connection) as queries:
                TestModel.objects.bulk_update(objs, ["test_char_field"])

        # Behaves as log_fields=False: the objects still get their keys.
        assert objs[0].pk is not None
        assert logging_queries(queries) == []
        assert not FieldLog.objects.exists()

    def test_async_bulk_operations_are_not_logged(self):
        with disable_logging():
            (obj,) = async_to_sync(TestModel.objects.all().abulk_create)(
                [TestModel(test_char_field="new")]
            )

        assert not obj.fieldlog_set.exists()

    def test_direct_calls_still_log(self):
        instance = TestModel.objects.create()
        TestModel.objects.filter(pk=instance.pk).update(test_char_field="new")

        with disable_logging():
            fieldlogger.log_fields(TestModel, [instance])

        assert char_logs(instance).get().new_value == "new"


def test_blocks_can_be_nested():
    with disable_logging():
        with disable_logging():
            assert logging_disabled()
        assert logging_disabled()
    assert not logging_disabled()


def test_restored_after_an_exception():
    with pytest.raises(ValueError), disable_logging():
        raise ValueError
    assert not logging_disabled()


def test_works_as_a_decorator():
    @disable_logging()
    def load():
        return logging_disabled()

    assert load()
    assert not logging_disabled()


def test_other_threads_keep_logging():
    """A thread already running, like another request, is not affected by
    a block entered in this one."""
    entered, checked = threading.Event(), threading.Event()
    seen = []

    def other_request():
        entered.wait()
        seen.append(logging_disabled())
        checked.set()

    thread = threading.Thread(target=other_request)
    thread.start()
    with disable_logging():
        entered.set()
        checked.wait()
    thread.join()

    assert seen == [False]
