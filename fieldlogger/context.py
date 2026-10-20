"""State that applies to a block of code: disabling logging, and who makes
the changes.

The state lives in ``ContextVar``s, so it only applies to the current
thread or async task: other threads (e.g. concurrent requests) are not
affected. Kept free of Django imports so that the package can re-export
these helpers before the app registry is ready.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, NamedTuple

_disabled: ContextVar[bool] = ContextVar("fieldlogger_disabled", default=False)


def logging_disabled() -> bool:
    """Whether ``disable_logging()`` is active in the current context."""
    return _disabled.get()


@contextmanager
def disable_logging() -> Iterator[None]:
    """Disable logging inside the ``with`` block or the decorated function.

    Saves, many-to-many changes and the bulk operations of
    ``FieldLoggerQuerySet`` create no logs and run no callbacks, and the
    queries that read the previous values are skipped. Direct calls to
    ``log_fields()`` and ``log_m2m_fields()`` still log. Blocks can be
    nested.
    """
    token = _disabled.set(True)
    try:
        yield
    finally:
        _disabled.reset(token)


class Actor(NamedTuple):
    """Who makes the changes logged inside a ``set_actor()`` block."""

    user: Any
    remote_addr: str | None


_actor: ContextVar[Actor | None] = ContextVar("fieldlogger_actor", default=None)


def current_actor() -> Actor | None:
    """The ``set_actor()`` values active in the current context, if any."""
    return _actor.get()


@contextmanager
def set_actor(user: Any, remote_addr: str | None = None) -> Iterator[None]:
    """Record ``user`` and ``remote_addr`` in the logs created inside the
    ``with`` block or the decorated function.

    ``user`` is an instance of the user model, or a lazy object such as
    ``request.user``: it is only evaluated when a log is created, and
    unauthenticated users are not recorded. Blocks can be nested; the
    innermost one applies.
    """
    token = _actor.set(Actor(user, remote_addr))
    try:
        yield
    finally:
        _actor.reset(token)
