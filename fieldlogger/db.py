"""Primary key handling for bulk inserts across database backends.

``bulk_create`` sets the primary keys of the inserted objects only on
backends that can return them (PostgreSQL, MariaDB, SQLite >= 3.35), and
never with ``ignore_conflicts``. Logs need those keys to reference their
instances, so where Django does not set them they are assigned here.
"""

from typing import Optional, Sequence, Type

from django.db import connections, router, transaction
from django.db.models import Max, Model


def db_supports_returning_pks(
    model_class: Type[Model], using: Optional[str] = None
) -> bool:
    """Return whether the database that ``model_class`` writes to sets
    primary keys on bulk-created objects."""
    using = using or router.db_for_write(model_class)
    return connections[using].features.can_return_rows_from_bulk_insert


def set_primary_keys(
    objs: Sequence[Model], model_class: Type[Model], using: Optional[str] = None
) -> None:
    """Assign sequential primary keys to ``objs`` before a bulk insert.

    Objects that already have a primary key are left untouched.

    Concurrent bulk inserts may compute the same starting key; callers that
    need concurrency must serialize these operations.
    """
    using = using or router.db_for_write(model_class)
    with transaction.atomic(using=using):
        next_pk = (
            model_class._base_manager.using(using).aggregate(max_pk=Max("pk"))["max_pk"]
            or 0
        )
        for obj in objs:
            if obj.pk is None:
                next_pk += 1
                obj.pk = next_pk
