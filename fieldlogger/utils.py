from functools import reduce
from typing import Any, Optional

from django.db.models import Model


def rgetattr(obj: object, rattr: str) -> Any:
    rattr = rattr.replace(".", "__").split("__")
    return reduce(getattr, rattr, obj)


def rhasattr(obj: object, rattr: str) -> bool:
    rattr = rattr.replace(".", "__").split("__")
    obj = reduce(getattr, rattr[:-1], obj)
    return hasattr(obj, rattr[-1])


def rsetattr(obj: object, rattr: str, val: Any) -> None:
    rattr = rattr.replace(".", "__").split("__")
    obj = reduce(getattr, rattr[:-1], obj)
    setattr(obj, rattr[-1], val)


def getrmodel(cls: Model, rfield: str) -> Optional[Model]:
    rfield = rfield.replace(".", "__").split("__")

    def _getrmodel(c, attr):
        return getattr(c, attr).field.related_model if hasattr(c, attr) else None

    return reduce(_getrmodel, rfield, cls)


def hasrmodel(cls: Model, rfield: str) -> bool:
    rfield = rfield.replace(".", "__").split("__")

    def _hasrmodel(c, attr):
        return hasattr(c, attr) and getattr(c, attr).field.related_model

    return bool(reduce(_hasrmodel, rfield, cls))
