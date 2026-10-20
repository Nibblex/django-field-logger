"""Test settings without django.contrib.auth (see test_actor.py): the
library must not require a user model."""

from .settings import *  # noqa: F403

INSTALLED_APPS = [
    "fieldlogger",
    "tests.testapp.apps.TestAppConfig",
]
