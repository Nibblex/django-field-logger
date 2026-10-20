"""Recording who made the change: set_actor() and FieldLoggerMiddleware."""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from asgiref.sync import async_to_sync, iscoroutinefunction, sync_to_async
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponse
from django.test import AsyncRequestFactory, RequestFactory
from django.utils.functional import SimpleLazyObject

from fieldlogger import set_actor
from fieldlogger.context import current_actor
from fieldlogger.middleware import FieldLoggerMiddleware
from fieldlogger.models import FieldLog

from .helpers import set_config
from .testapp.models import TestModel, TestModelRelated2

User = get_user_model()


@pytest.fixture
def user():
    return User.objects.create_user(username="alice")


def actor_of(log):
    return (log.actor_id, log.actor_username, log.remote_addr)


def char_log(instance=None):
    """The latest log of test_char_field, of ``instance`` or of any."""
    logs = instance.fieldlog_set if instance else FieldLog.objects
    return logs.filter(field="test_char_field").latest("pk")


@pytest.mark.django_db(transaction=True)
class TestSetActor:
    def test_records_the_user_and_address(self, user):
        with set_actor(user, remote_addr="10.0.0.1"):
            instance = TestModel.objects.create(test_char_field="old")
            instance.test_char_field = "new"
            instance.save()

        logs = instance.fieldlog_set.filter(field="test_char_field")
        assert [actor_of(log) for log in logs] == [
            (str(user.pk), "alice", "10.0.0.1")
        ] * 2

    def test_logs_outside_a_block_have_no_actor(self):
        instance = TestModel.objects.create(test_char_field="new")

        assert actor_of(char_log(instance)) == (None, None, None)

    def test_bulk_operations_record_the_user(self, user):
        with set_actor(user):
            (obj,) = TestModel.objects.bulk_create([TestModel(test_char_field="old")])
            obj.test_char_field = "new"
            TestModel.objects.bulk_update([obj], ["test_char_field"])

        logs = obj.fieldlog_set.filter(field="test_char_field")
        assert [log.actor_id for log in logs] == [str(user.pk)] * 2

    def test_m2m_changes_record_the_user(self, user):
        instance = TestModel.objects.create()
        with set_actor(user):
            instance.test_many_to_many_field.add(TestModelRelated2.objects.create())

        log = instance.fieldlog_set.get(field="test_many_to_many_field")
        assert log.actor_id == str(user.pk)

    @pytest.mark.usefixtures("restore_settings")
    def test_callbacks_see_the_actor(self, user):
        seen = []

        def callback(instance, fields, logs):
            seen.extend(log.actor_username for log in logs.values())

        set_config({"callbacks": [callback]}, "testmodel")
        with set_actor(user):
            TestModel.objects.create(test_char_field="new")

        assert seen == ["alice"]

    @pytest.mark.parametrize("anonymous", [None, AnonymousUser()])
    def test_unauthenticated_users_are_not_recorded(self, anonymous):
        with set_actor(anonymous, remote_addr="10.0.0.1"):
            instance = TestModel.objects.create(test_char_field="new")

        assert actor_of(char_log(instance)) == (None, None, "10.0.0.1")

    def test_unsaved_users_are_not_recorded(self):
        with set_actor(User(username="ghost")):
            instance = TestModel.objects.create(test_char_field="new")

        assert char_log(instance).actor_id is None

    def test_long_usernames_are_truncated(self):
        # Unsaved, so the username does not have to fit the user table.
        with set_actor(User(pk=1000, username="x" * 300)):
            instance = TestModel.objects.create(test_char_field="new")

        log = char_log(instance)
        assert (log.actor_id, log.actor_username) == ("1000", "x" * 255)

    @pytest.mark.parametrize(
        "remote_addr, stored",
        [
            ("192.168.0.1", "192.168.0.1"),
            ("2001:DB8::1", "2001:db8::1"),
            # Malformed values, e.g. read from a header, are not stored:
            # the database could reject them.
            ("unknown", None),
            ("10.0.0.1, 10.0.0.2", None),
            ("fe80::1%eth0", None),
            ("", None),
        ],
    )
    def test_remote_addr_is_validated(self, remote_addr, stored):
        with set_actor(None, remote_addr=remote_addr):
            instance = TestModel.objects.create(test_char_field="new")

        assert char_log(instance).remote_addr == stored

    @pytest.mark.usefixtures("restore_settings")
    def test_remote_addr_can_be_disabled(self, user):
        set_config({"log_remote_addr": False}, "global")
        with set_actor(user, remote_addr="10.0.0.1"):
            instance = TestModel.objects.create(test_char_field="new")

        assert actor_of(char_log(instance)) == (str(user.pk), "alice", None)

    def test_the_innermost_block_applies(self, user):
        other = User.objects.create_user(username="bob")
        with set_actor(user, remote_addr="10.0.0.1"):
            with set_actor(other):
                inner = TestModel.objects.create(test_char_field="inner")
            outer = TestModel.objects.create(test_char_field="outer")

        assert actor_of(char_log(inner)) == (str(other.pk), "bob", None)
        assert actor_of(char_log(outer)) == (str(user.pk), "alice", "10.0.0.1")
        assert current_actor() is None

    def test_lazy_user_is_only_evaluated_when_logging(self, user):
        evaluated = []

        def load():
            evaluated.append(True)
            return user

        with set_actor(SimpleLazyObject(load)):
            TestModelRelated2.objects.create()  # Not logged.
            assert evaluated == []
            instance = TestModel.objects.create(test_char_field="new")

        assert evaluated == [True]
        assert char_log(instance).actor_id == str(user.pk)

    def test_actor_property(self, user):
        with set_actor(user):
            instance = TestModel.objects.create(test_char_field="new")
        log = char_log(instance)
        assert log.actor == user

        # Deleting the user keeps who it was.
        user_id = str(user.pk)
        user.delete()
        log = FieldLog.objects.get(pk=log.pk)
        assert log.actor is None
        assert (log.actor_id, log.actor_username) == (user_id, "alice")

    def test_actor_property_without_actor(self):
        instance = TestModel.objects.create(test_char_field="new")

        assert char_log(instance).actor is None


def save_view(request):
    TestModel.objects.create(test_char_field="via request")
    return HttpResponse()


async def async_save_view(request):
    await sync_to_async(TestModel.objects.create)(test_char_field="via request")
    return HttpResponse()


@pytest.mark.django_db(transaction=True)
class TestFieldLoggerMiddleware:
    def test_records_the_request_user_and_address(self, user):
        request = RequestFactory().get("/", REMOTE_ADDR="10.0.0.1")
        request.user = user

        FieldLoggerMiddleware(save_view)(request)

        assert actor_of(char_log()) == (str(user.pk), "alice", "10.0.0.1")

    def test_async_requests(self, user):
        request = AsyncRequestFactory().get("/")
        request.user = user
        middleware = FieldLoggerMiddleware(async_save_view)

        assert iscoroutinefunction(middleware)
        async_to_sync(middleware)(request)

        assert actor_of(char_log()) == (str(user.pk), "alice", "127.0.0.1")

    def test_anonymous_requests_record_only_the_address(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()

        FieldLoggerMiddleware(save_view)(request)

        assert actor_of(char_log()) == (None, None, "127.0.0.1")

    def test_requests_without_a_user(self):
        """Without AuthenticationMiddleware before it, there is no
        request.user."""
        FieldLoggerMiddleware(save_view)(RequestFactory().get("/"))

        assert actor_of(char_log()) == (None, None, "127.0.0.1")

    def test_requests_that_log_nothing_do_not_load_the_user(self, user):
        evaluated = []
        request = RequestFactory().get("/")
        request.user = SimpleLazyObject(lambda: evaluated.append(True) or user)

        FieldLoggerMiddleware(lambda request: HttpResponse())(request)

        assert evaluated == []

    def test_remote_addr_from_a_trusted_header(self):
        class ProxyMiddleware(FieldLoggerMiddleware):
            def get_remote_addr(self, request):
                return request.headers.get("X-Real-IP")

        request = RequestFactory().get("/", HTTP_X_REAL_IP="203.0.113.7")
        ProxyMiddleware(save_view)(request)

        assert char_log().remote_addr == "203.0.113.7"


NO_AUTH_SCRIPT = """
import django

django.setup()

from django.core.management import call_command
from django.http import HttpResponse
from django.test import RequestFactory

from fieldlogger.middleware import FieldLoggerMiddleware
from fieldlogger.models import FieldLog
from tests.testapp.models import TestModel

call_command("migrate", run_syncdb=True, verbosity=0)


def view(request):
    TestModel.objects.create(test_char_field="new")
    return HttpResponse()


FieldLoggerMiddleware(view)(RequestFactory().get("/"))
log = FieldLog.objects.get(field="test_char_field")
assert (log.actor_id, log.actor, log.remote_addr) == (None, None, "127.0.0.1")
"""


def test_works_without_django_contrib_auth(tmp_path):
    """The user model is optional: without django.contrib.auth, logs are
    still created through the middleware, with the address and no user."""
    env = {
        name: value
        for name, value in os.environ.items()
        # pytest-cov measures subprocesses through these variables; the
        # child would report its own files with a wider source.
        if not name.startswith("COV_CORE_") and name != "COVERAGE_PROCESS_START"
    }
    env["PYTHONPATH"] = str(Path(__file__).parent.parent)
    env["DJANGO_SETTINGS_MODULE"] = "tests.settings_no_auth"
    env.pop("TEST_DB", None)  # SQLite, created in tmp_path.

    result = subprocess.run(
        [sys.executable, "-c", NO_AUTH_SCRIPT],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
