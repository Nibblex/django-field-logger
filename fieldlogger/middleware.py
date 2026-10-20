"""Middleware that records who makes the changes logged during a request."""

from collections.abc import Callable
from typing import Any

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.http import HttpRequest

from .context import set_actor


class FieldLoggerMiddleware:
    """Records the request's user and IP address in the logs created while
    handling it, through ``set_actor()``.

    Place it after ``AuthenticationMiddleware``. ``request.user`` is only
    evaluated if a log is created. Override ``get_user()`` or
    ``get_remote_addr()`` to change where they come from, e.g. to read the
    client's address from a header set by a trusted proxy.
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
        with set_actor(self.get_user(request), self.get_remote_addr(request)):
            return self.get_response(request)

    async def __acall__(self, request: HttpRequest) -> Any:
        with set_actor(self.get_user(request), self.get_remote_addr(request)):
            return await self.get_response(request)

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
