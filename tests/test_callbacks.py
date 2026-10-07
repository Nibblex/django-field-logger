import pytest

from fieldlogger.callbacks import invoke_callbacks

from .testapp.models import TestModel


def test_failing_callback_is_logged_when_fail_silently(caplog):
    received = []

    def bad_callback(*args):
        raise ValueError("boom")

    invoke_callbacks(
        [TestModel()],
        [bad_callback, lambda *args: received.append(args)],
        {},
        frozenset(),
        fail_silently=True,
    )

    assert "bad_callback" in caplog.text
    # The remaining callbacks still run.
    assert len(received) == 1


def test_failing_callback_propagates_without_fail_silently():
    def bad_callback(*args):
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        invoke_callbacks([TestModel()], [bad_callback], {}, frozenset())


def test_callbacks_receive_the_logs_of_their_instance():
    first, second = TestModel(pk=1), TestModel(pk=2)
    received = {}
    logs = {1: {"f": "log of 1"}}

    invoke_callbacks(
        [first, second],
        [lambda instance, fields, logs: received.update({instance.pk: logs})],
        logs,
        frozenset(),
    )

    assert received == {1: {"f": "log of 1"}, 2: {}}
