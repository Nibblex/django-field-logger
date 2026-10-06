from copy import deepcopy

import pytest
from django.conf import settings
from django.db import connections

from .helpers import refresh_config

ORIGINAL_SETTINGS = deepcopy(settings.FIELD_LOGGER_SETTINGS)


@pytest.fixture
def no_returning_pks(monkeypatch):
    """Make bulk_create behave as on backends that cannot return primary
    keys from bulk inserts (MySQL, Oracle, SQLite < 3.35): Django leaves
    the keys of the inserted objects unset."""
    for alias in connections:
        monkeypatch.setattr(
            type(connections[alias].features),
            "can_return_rows_from_bulk_insert",
            False,
        )


@pytest.fixture
def restore_settings():
    yield
    settings.FIELD_LOGGER_SETTINGS = deepcopy(ORIGINAL_SETTINGS)
    refresh_config()
