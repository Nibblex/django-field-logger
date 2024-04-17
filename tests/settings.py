import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "test_db",
    }
}

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
