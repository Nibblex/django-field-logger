"""Database backend differences: query size limits and primary keys of
bulk inserts.

``bulk_create`` sets the primary keys of the inserted objects only on
backends that can return them (PostgreSQL, MariaDB, SQLite >= 3.35), and
never with ``ignore_conflicts``. Logs need those keys to reference their
instances, so where Django does not set them they are assigned here.
"""

from typing import Any, Iterator, List, Optional, Sequence, Tuple, Type, TypeVar

from django.db import connections, router
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.models import Max, Model
from django.db.models.fields import Field

_T = TypeVar("_T")


def batches(
    values: Sequence[_T],
    fields: Sequence[Field],
    using: Optional[str] = None,
    max_size: Optional[int] = None,
) -> Iterator[List[_T]]:
    """Split ``values`` into chunks that fit in one query.

    ``fields`` are the fields each value contributes a parameter for (one
    for a ``field__in`` lookup, several when every value is matched on
    many fields). The size comes from the backend (``bulk_batch_size``):
    a single chunk where queries have no parameter limit (PostgreSQL,
    MySQL), several on SQLite (999 parameters before 3.32) or Oracle.
    ``max_size`` caps it for limits that do not depend on parameters.
    """
    using = using or router.db_for_write(fields[0].model)
    size = max(connections[using].ops.bulk_batch_size(list(fields), values), 1)
    if max_size is not None:
        size = min(size, max_size)
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def db_supports_returning_pks(
    model_class: Type[Model], using: Optional[str] = None
) -> bool:
    """Return whether the database that ``model_class`` writes to sets
    primary keys on bulk-created objects."""
    using = using or router.db_for_write(model_class)
    return connections[using].features.can_return_rows_from_bulk_insert


def _nextval_sql(
    connection: BaseDatabaseWrapper, sequence: str, count: int
) -> Optional[Tuple[str, List[Any]]]:
    """Query returning ``count`` values of ``sequence``, on backends whose
    primary keys come from a named sequence; None elsewhere."""
    name = connection.ops.quote_name(sequence)
    if connection.vendor == "postgresql":
        return "SELECT nextval(%s) FROM generate_series(1, %s)", [name, count]
    if connection.vendor == "oracle":
        return f"SELECT {name}.NEXTVAL FROM DUAL CONNECT BY LEVEL <= %s", [count]
    return None


def _reserve_from_sequence(
    model_class: Type[Model], using: str, count: int
) -> Optional[List[Any]]:
    """Take ``count`` values from the sequence of the primary key of
    ``model_class``, or None if it has none (SQLite, MySQL)."""
    connection = connections[using]
    column = model_class._meta.pk.column
    with connection.cursor() as cursor:
        try:
            sequences = connection.introspection.get_sequences(
                cursor, model_class._meta.db_table
            )
        except NotImplementedError:
            # Third-party backends without sequence introspection.
            return None
        name = next(
            (seq.get("name") for seq in sequences if seq["column"] == column), None
        )
        query = _nextval_sql(connection, name, count) if name else None
        if query is None:
            return None
        cursor.execute(*query)
        return [row[0] for row in cursor.fetchall()]


def reserve_primary_keys(
    objs: Sequence[Model], model_class: Type[Model], using: Optional[str] = None
) -> None:
    """Assign primary keys to ``objs`` before a bulk insert. Objects that
    already have one are left untouched.

    On PostgreSQL and Oracle the keys are taken from the primary key's
    sequence: they are reserved, so no other insert, concurrent or later,
    gets them, and the sequence needs no reset afterwards. Elsewhere
    (SQLite, MySQL, whose auto-increment counters follow explicit keys)
    they continue from the highest key in the table; concurrent bulk
    inserts may then compute the same keys, so callers that need
    concurrency there must serialize these operations.
    """
    using = using or router.db_for_write(model_class)
    unsaved = [obj for obj in objs if obj.pk is None]
    if not unsaved:
        return

    reserved = _reserve_from_sequence(model_class, using, len(unsaved))
    if reserved is not None:
        keys = reserved
    else:
        highest = (
            model_class._base_manager.using(using).aggregate(max_pk=Max("pk"))["max_pk"]
            or 0
        )
        keys = list(range(highest + 1, highest + 1 + len(unsaved)))

    for obj, key in zip(unsaved, keys):
        obj.pk = key
