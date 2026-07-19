"""A Django app for logging changes in model fields."""

# Needed for Django < 3.2, which does not auto-discover AppConfig classes;
# without it the app's ready() never runs and the signals are not connected.
# Ignored (and deprecated) on Django >= 3.2.
default_app_config = "fieldlogger.apps.FieldloggerConfig"
