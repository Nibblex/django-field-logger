"""Access to the raw ``FIELD_LOGGER_SETTINGS`` dict.

Kept free of package imports so that any module (notably ``encoding``,
which ``models`` depends on) can read the settings without creating an
import cycle.
"""

from django.conf import settings


def get_settings() -> dict:
    """Return the ``FIELD_LOGGER_SETTINGS`` dict from the Django settings."""
    return getattr(settings, "FIELD_LOGGER_SETTINGS", {})
