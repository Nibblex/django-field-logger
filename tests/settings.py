import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SECRET_KEY = "dummy"

MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "test_db",
    },
    "other": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "test_db_other",
    },
}

# Run the suite against another database server with TEST_DB set to
# postgres, mysql, mariadb or oracle (see the matching tox factors).
# Connection settings come from DB_HOST, DB_PORT, DB_USER and DB_PASSWORD.
_BACKENDS = {
    "postgres": ("django.db.backends.postgresql", "5432", "postgres"),
    "mysql": ("django.db.backends.mysql", "3306", "root"),
    "mariadb": ("django.db.backends.mysql", "3306", "root"),
    "oracle": ("django.db.backends.oracle", "1521", "system"),
}
TEST_DB = os.environ.get("TEST_DB", "sqlite")

if TEST_DB != "sqlite":
    engine, port, user = _BACKENDS[TEST_DB]
    connection = {
        "ENGINE": engine,
        "HOST": os.environ.get("DB_HOST", "localhost"),
        "PORT": os.environ.get("DB_PORT", port),
        "USER": os.environ.get("DB_USER", user),
        "PASSWORD": os.environ["DB_PASSWORD"],
    }
    if TEST_DB == "oracle":
        # NAME is the service, given as host:port/service: with HOST and
        # PORT set, Django would take it as a SID. Each alias gets its own
        # test user (schema) inside the same database.
        service = os.environ.get("DB_NAME", "FREEPDB1")
        DATABASES = {
            alias: {
                **connection,
                "HOST": "",
                "PORT": "",
                "NAME": f"{connection['HOST']}:{connection['PORT']}/{service}",
                # Tablespaces are named after NAME by default, shared by
                # both aliases: creating one would drop the other's.
                "TEST": {
                    "USER": f"fl_{alias}",
                    "PASSWORD": "fieldlogger",
                    "TBLSPACE": f"fl_{alias}",
                    "TBLSPACE_TMP": f"fl_{alias}_tmp",
                },
            }
            for alias in ("default", "other")
        }
    else:
        DATABASES = {
            alias: {**connection, "NAME": f"fieldlogger_{alias}"}
            for alias in ("default", "other")
        }

    if engine == "django.db.backends.mysql":
        import pymysql

        # Django requires a MySQLdb module; PyMySQL is pure Python (no
        # client libraries needed) and can stand in for it.
        pymysql.version_info = (2, 2, 1, "final", 0)
        pymysql.install_as_MySQLdb()

INSTALLED_APPS = [
    "fieldlogger",
    "tests.testapp.apps.TestAppConfig",
]

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
        "file": {
            "class": "logging.FileHandler",
            "filename": os.path.join(BASE_DIR, "debug.log"),
        },
    },
    "loggers": {
        "root": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": True,
        },
    },
}


def get_callback(scope):
    def callback(instance, using_fields, logs):
        for log in logs.values():
            log.extra_data[scope] = True
            log.save(update_fields=["extra_data"])

    return callback


FIELD_LOGGER_SETTINGS = {
    "CALLBACKS": [get_callback("global")],
    "LOGGING_APPS": {
        "testapp": {
            "callbacks": [get_callback("testapp")],
            "models": {
                "TestModel": {
                    "callbacks": [get_callback("testmodel")],
                    "fields": "__all__",
                    "exclude_fields": ["id"],
                },
            },
        },
    },
}

# Internationalization
# https://docs.djangoproject.com/en/4.0/topics/i18n/

LANGUAGE_CODE = "en-us"

TIME_ZONE = "America/Argentina/Cordoba"

USE_I18N = True

USE_TZ = True
