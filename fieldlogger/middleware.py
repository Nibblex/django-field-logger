"""Middleware that records who makes the changes logged during a request,
and groups their logs."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import HttpRequest

from .context import set_actor, set_correlation_id


class FieldLoggerMiddleware:
    """Records the request's user and IP address in the logs created while
    handling it, through ``set_actor()``, and gives them a correlation ID of
    the request, through ``set_correlation_id()``.

    Place it after ``AuthenticationMiddleware``. ``request.user`` is only
    evaluated if a log is created. Override ``get_user()``,
    ``get_remote_addr()`` or ``get_correlation_id()`` to change where they
    come from, e.g. to read the client's address from a header set by a
    trusted proxy.
    """

    sync_capable = True
    async_capable = True

    def __init__(self, get_response: Callable[[HttpRequest], Any]) -> None:
        self.get_response = get_response
        self.async_mode = iscoroutinefunction(get_response)
        if self.async_mode:
            # Django then awaits the instance; __call__ hands over to
            # __acall__, as Django's own MiddlewareMixin does.
            markcoroutinefunction(self)

    def __call__(self, request: HttpRequest) -> Any:
        if self.async_mode:
            return self.__acall__(request)
        with self._logging_context(request):
            return self.get_response(request)

    async def __acall__(self, request: HttpRequest) -> Any:
        with self._logging_context(request):
            return await self.get_response(request)

    @contextmanager
    def _logging_context(self, request: HttpRequest) -> Iterator[None]:
        with (
            set_actor(self.get_user(request), self.get_remote_addr(request)),
            set_correlation_id(self.get_correlation_id(request)),
        ):
            yield

    def get_user(self, request: HttpRequest) -> Any:
        """The user to record: ``request.user``, still unevaluated."""
        return getattr(request, "user", None)

    def get_remote_addr(self, request: HttpRequest) -> str | None:
        """The client's IP address: ``REMOTE_ADDR``.

        Behind a reverse proxy this is the proxy's address. Do not read
        ``X-Forwarded-For`` unless your proxy sets it: clients can send it
        with any value.
        """
        return request.META.get("REMOTE_ADDR")

    def get_correlation_id(self, request: HttpRequest) -> Any:
        """The correlation ID of the request's logs: None, so that each
        request gets a new random one.

        Return the ID of the request from elsewhere to match it, e.g. a
        header set by your proxy or the ID of a request-ID library. An
        empty value also gets a new random ID.
        """
        return None
