"""Disabling logging for a block of code.

The state lives in a ``ContextVar``, so it only applies to the current
thread or async task: other threads (e.g. concurrent requests) keep
logging. Kept free of Django imports so that the package can re-export
``disable_logging`` before the app registry is ready.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

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
