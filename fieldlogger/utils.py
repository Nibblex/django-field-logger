from functools import reduce
from typing import Optional

from django.db.models import Model


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
