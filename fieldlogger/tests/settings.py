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
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "fieldlogger",
    "fieldlogger.tests.testapp.apps.TestAppConfig",
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


def failing_callback(instance, using_fields, logs):
    raise Exception("This is a test exception.")


FIELD_LOGGER_SETTINGS = {
    "CALLBACKS": [get_callback("global")],
    "LOGGING_APPS": {
        "testapp": {
            "callbacks": [get_callback("testapp")],
            "models": {
                "TestModel": {
                    "callbacks": [failing_callback],
                    "fields": [
                        "test_big_integer_field",
                        "test_binary_field",
                        "test_boolean_field",
                        "test_char_field",
                        "test_date_field",
                        "test_datetime_field",
                        "test_decimal_field",
                        "test_duration_field",
                        "test_email_field",
                        "test_file_field",
                        "test_file_path_field",
                        "test_float_field",
                        "test_generic_ip_address_field",
                        "test_image_field",
                        "test_integer_field",
                        "test_json_field",
                        "test_positive_big_integer_field",
                        "test_positive_integer_field",
                        "test_positive_small_integer_field",
                        "test_slug_field",
                        "test_small_integer_field",
                        "test_text_field",
                        "test_time_field",
                        "test_url_field",
                        "test_uuid_field",
                    ],
                },
            },
        },
    },
}
