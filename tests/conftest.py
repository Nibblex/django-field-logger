import os

import pytest

DB_CONFIGS = {
    "sqlite": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    },
    "postgresql": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "fieldlogger_test"),
        "USER": os.environ.get("POSTGRES_USER", "postgres"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", ""),
        "HOST": os.environ.get("POSTGRES_HOST", "localhost"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "TEST": {
            "NAME": os.environ.get("POSTGRES_TEST_DB", "test_fieldlogger"),
        },
    },
    "mysql": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ.get("MYSQL_DB", "fieldlogger_test"),
        "USER": os.environ.get("MYSQL_USER", "root"),
        "PASSWORD": os.environ.get("MYSQL_PASSWORD", ""),
        "HOST": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "PORT": os.environ.get("MYSQL_PORT", "3306"),
        "TEST": {
            "NAME": os.environ.get("MYSQL_TEST_DB", "test_fieldlogger"),
        },
    },
}


def _switch_database(db_config):
    """Reset Django's connection handler to use *db_config* as the new DATABASES."""
    from django.conf import settings
    from django.db import connections

    settings.DATABASES = db_config

    # Close every open connection before we throw away the handler state.
    connections.close_all()

    if hasattr(connections, "_settings"):
        # Django 4.0+ (BaseConnectionHandler): settings is a cached_property.
        # Pop the cached value so the getter is called again on next access.
        connections.__dict__.pop("settings", None)
        # Also reset _settings to None so that configure_settings() re-reads
        # from settings.DATABASES instead of returning the stale old dict.
        connections._settings = None
    elif hasattr(connections, "_databases"):
        # Django 3.x (old ConnectionHandler): update the stored databases dict.
        connections._databases = db_config

    # Replace thread-local storage so stale connection objects are discarded.
    try:
        from asgiref.local import Local

        thread_critical = getattr(connections, "thread_critical", False)
        connections._connections = Local(thread_critical)
    except (ImportError, AttributeError):
        pass


@pytest.fixture(scope="session", params=["sqlite", "mysql", "postgresql"])
def django_db_setup(request, django_test_environment, django_db_blocker):
    from importlib import reload

    import fieldlogger.config as config_module
    import fieldlogger.fieldlogger as fieldlogger_module
    import fieldlogger.signals as signals_module
    from django.test.utils import setup_databases, teardown_databases

    backend = request.param
    db_config = {"default": DB_CONFIGS[backend]}

    # Switch Django's active database to the selected backend.
    _switch_database(db_config)

    # Attempt to create the test database.  If the driver is not installed or the
    # server is unreachable this will raise – we convert that into a skip so the
    # rest of the test suite continues without the missing backend.
    with django_db_blocker.unblock():
        try:
            old_db = setup_databases(
                verbosity=request.config.option.verbose,
                interactive=False,
                keepdb=False,
            )
        except Exception as exc:
            pytest.skip(f"Cannot set up {backend!r} database: {exc}")

    # Reload fieldlogger *after* the database is confirmed reachable so that
    # config.py can safely inspect connection.vendor / DB_VERSION.
    reload(config_module)
    reload(fieldlogger_module)
    reload(signals_module)

    yield

    with django_db_blocker.unblock():
        teardown_databases(old_db, verbosity=request.config.option.verbose)


@pytest.fixture(autouse=True)
def _db_backend(django_db_setup):
    """Autouse fixture that makes every test inherit the django_db_setup parametrize.

    Declaring a direct dependency on the parametrized ``django_db_setup`` fixture
    ensures that pytest propagates the backend parameter to each test item during
    collection, so that the mark-injected ``transactional_db``/``db`` fixtures can
    resolve the correct session-scoped instance.
    """
    pass

