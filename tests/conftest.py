from copy import deepcopy

import pytest
from django.conf import settings

from .helpers import refresh_config

ORIGINAL_SETTINGS = deepcopy(settings.FIELD_LOGGER_SETTINGS)


@pytest.fixture
def restore_settings():
    yield
    settings.FIELD_LOGGER_SETTINGS = deepcopy(ORIGINAL_SETTINGS)
    refresh_config()
