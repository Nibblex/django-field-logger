"""Helpers to resolve related-field paths like ``"fk1__fk2"`` or ``"fk1.fk2"``."""

from functools import reduce

from django.db.models import Model


def getrmodel(cls: type[Model], rfield: str) -> type[Model] | None:
    """Return the model class that the related-field path ``rfield`` points
    to from ``cls``, or ``None`` if the path does not resolve to a relation."""
    attrs = rfield.replace(".", "__").split("__")

    def _getrmodel(c: type[Model] | None, attr: str) -> type[Model] | None:
        # Attributes that are not field descriptors (e.g. properties or
        # managers) have no ``field`` and do not resolve.
        field = getattr(getattr(c, attr, None), "field", None)
        return field.related_model if field is not None else None

    initial: type[Model] | None = cls
    return reduce(_getrmodel, attrs, initial)


def hasrmodel(cls: type[Model], rfield: str) -> bool:
    """Return whether the related-field path ``rfield`` resolves to a
    relation from ``cls``."""
    return getrmodel(cls, rfield) is not None
