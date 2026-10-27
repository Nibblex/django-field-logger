"""Grouping logs: set_correlation_id() and the request's correlation ID."""

from uuid import UUID

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from django.http import HttpResponse
from django.test import AsyncRequestFactory, RequestFactory

from fieldlogger import set_correlation_id
from fieldlogger.context import current_correlation_id
from fieldlogger.middleware import FieldLoggerMiddleware
from fieldlogger.models import FieldLog

from .testapp.models import TestModel, TestModelRelated2


def correlation_ids(logs):
    return {log.correlation_id for log in logs}


def is_uuid(value):
    return str(UUID(value)) == value


@pytest.mark.django_db(transaction=True)
class TestOutsideABlock:
    def test_the_logs_of_an_operation_share_an_id(self):
        instance = TestModel.objects.create(test_char_field="a", test_integer_field=1)
        created_ids = correlation_ids(instance.fieldlog_set.all())

        instance.test_char_field = "b"
        instance.save()
        update_ids = correlation_ids(instance.fieldlog_set.filter(created=False))

        assert len(created_ids) == 1
        assert is_uuid(*created_ids)
        assert len(update_ids) == 1
        assert update_ids != created_ids

    def test_bulk_operations_share_an_id(self):
        TestModel.objects.bulk_create(
            [TestModel(test_char_field="a"), TestModel(test_char_field="b")]
        )

        assert len(correlation_ids(FieldLog.objects.all())) == 1

    def test_m2m_changes_share_an_id(self):
        """A change from the reverse side logs every related instance."""
        instances = [TestModel.objects.create(), TestModel.objects.create()]
        FieldLog.objects.all().delete()
        related = TestModelRelated2.objects.create()
        related.test_reverse_m2m.add(*instances)

        logs = FieldLog.objects.filter(field="test_many_to_many_field")
        assert logs.count() == 2
        assert len(correlation_ids(logs)) == 1


@pytest.mark.django_db(transaction=True)
class TestSetCorrelationId:
    def test_groups_the_logs_of_the_block(self):
        with set_correlation_id("task-1") as correlation_id:
            instance = TestModel.objects.create(test_char_field="a")
            instance.test_char_field = "b"
            instance.save()
            TestModel.objects.bulk_create([TestModel(test_char_field="c")])

        assert correlation_id == "task-1"
        assert correlation_ids(FieldLog.objects.all()) == {"task-1"}

    @pytest.mark.parametrize("value", [None, ""])
    def test_a_new_id_without_a_value(self, value):
        with set_correlation_id(value) as correlation_id:
            TestModel.objects.create(test_char_field="a")

        assert is_uuid(correlation_id)
        assert correlation_ids(FieldLog.objects.all()) == {correlation_id}

    def test_values_are_stored_as_text(self):
        value = UUID("550e8400-e29b-41d4-a716-446655440000")
        with set_correlation_id(value) as correlation_id:
            TestModel.objects.create(test_char_field="a")

        assert correlation_id == str(value)
        assert correlation_ids(FieldLog.objects.all()) == {str(value)}

    def test_long_ids_are_truncated(self):
        with set_correlation_id("x" * 300):
            TestModel.objects.create(test_char_field="a")

        assert correlation_ids(FieldLog.objects.all()) == {"x" * 255}


def test_the_innermost_block_applies():
    with set_correlation_id("outer"):
        with set_correlation_id("inner"):
            assert current_correlation_id() == "inner"
        assert current_correlation_id() == "outer"
    assert current_correlation_id() is None


def test_each_call_of_a_decorated_function_gets_a_new_id():
    @set_correlation_id()
    def task():
        return current_correlation_id()

    first, second = task(), task()
    assert is_uuid(first)
    assert first != second


def save_view(request):
    TestModel.objects.create(test_char_field="a")
    TestModel.objects.create(test_char_field="b")
    return HttpResponse()


async def async_save_view(request):
    await sync_to_async(save_view)(request)
    return HttpResponse()


class RequestIdMiddleware(FieldLoggerMiddleware):
    """Takes the correlation ID from a header set by a proxy."""

    def get_correlation_id(self, request):
        return request.headers.get("X-Request-ID")


@pytest.mark.django_db(transaction=True)
class TestFieldLoggerMiddleware:
    def test_the_logs_of_a_request_share_an_id(self):
        middleware = FieldLoggerMiddleware(save_view)
        middleware(RequestFactory().get("/"))
        first = correlation_ids(FieldLog.objects.all())
        FieldLog.objects.all().delete()
        middleware(RequestFactory().get("/"))
        second = correlation_ids(FieldLog.objects.all())

        assert len(first) == 1
        assert is_uuid(*first)
        assert len(second) == 1
        assert second != first

    def test_async_requests(self):
        async_to_sync(FieldLoggerMiddleware(async_save_view))(
            AsyncRequestFactory().get("/")
        )

        ids = correlation_ids(FieldLog.objects.all())
        assert len(ids) == 1
        assert is_uuid(*ids)

    def test_the_id_from_a_header(self):
        request = RequestFactory().get("/", HTTP_X_REQUEST_ID="req-42")
        RequestIdMiddleware(save_view)(request)

        assert correlation_ids(FieldLog.objects.all()) == {"req-42"}

    def test_a_new_id_without_the_header(self):
        RequestIdMiddleware(save_view)(RequestFactory().get("/"))

        (correlation_id,) = correlation_ids(FieldLog.objects.all())
        assert is_uuid(correlation_id)
