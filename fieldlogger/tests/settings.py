import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MEDIA_ROOT = os.path.join(BASE_DIR, "media")
MEDIA_URL = "/media/"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "mem_db",
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
    },
    "loggers": {
        "root": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
    },
}


def global_callback(instance, using_fields, logs):
    for log in logs.values():
        log.extra_data["global"] = True
        log.save()


def testapp_callback(instance, using_fields, logs):
    for log in logs.values():
        log.extra_data["testapp"] = True
        log.save()


def testmodel_callback(instance, using_fields, logs):
    for log in logs.values():
        log.extra_data["testmodel"] = True
        log.save()


FIELD_LOGGER_SETTINGS = {
    "CALLBACKS": [global_callback],
    "LOGGING_APPS": {
        "testapp": {
            "callbacks": [testapp_callback],
            "models": {
                "TestModel": {
                    "callbacks": [testmodel_callback],
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
                    "exclude_fields": [],
                },
            },
        },
    },
}
