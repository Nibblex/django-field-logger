"""Helpers to resolve related-field paths like ``"fk1__fk2"`` or ``"fk1.fk2"``."""

from functools import reduce
from typing import Optional, Type

from django.db.models import Model


def getrmodel(cls: Type[Model], rfield: str) -> Optional[Type[Model]]:
    """Return the model class that the related-field path ``rfield`` points
    to from ``cls``, or ``None`` if the path does not resolve to a relation."""
    attrs = rfield.replace(".", "__").split("__")

    def _getrmodel(c, attr):
        # Attributes that are not field descriptors (e.g. properties or
        # managers) have no ``field`` and do not resolve.
        field = getattr(getattr(c, attr, None), "field", None)
        return field.related_model if field is not None else None

    return reduce(_getrmodel, attrs, cls)


def hasrmodel(cls: Type[Model], rfield: str) -> bool:
    """Return whether the related-field path ``rfield`` resolves to a
    relation from ``cls``."""
    return getrmodel(cls, rfield) is not None
