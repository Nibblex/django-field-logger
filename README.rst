.. image:: https://img.shields.io/pypi/pyversions/django-field-logger
   :target: https://www.python.org/
   :alt: PyPI - Python Version
.. image:: https://img.shields.io/pypi/frameworkversions/django/django-field-logger
   :target: https://www.djangoproject.com/
   :alt: PyPI - Django Version
.. image:: https://img.shields.io/pypi/v/django-field-logger?color=blue
   :target: https://pypi.org/project/django-field-logger/
   :alt: PyPI - Version
.. image:: https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json
   :target: https://github.com/astral-sh/ruff
   :alt: Ruff
.. image:: https://results.pre-commit.ci/badge/github/Nibblex/django-field-logger/main.svg
   :target: https://results.pre-commit.ci/latest/github/Nibblex/django-field-logger/main
   :alt: pre-commit.ci status
.. image:: https://codecov.io/gh/Nibblex/django-field-logger/graph/badge.svg?token=H1N619SS8P
   :target: https://codecov.io/gh/Nibblex/django-field-logger
   :alt: Codecov
.. image:: https://img.shields.io/pypi/l/django-field-logger
   :target: https://github.com/Nibblex/django-field-logger/blob/main/LICENSE
   :alt: PyPI - License

Django Field Logger
===================

A Django app for logging changes in model fields.

How to set up?
~~~~~~~~~~~~~~

1) Add ``fieldlogger`` to your ``INSTALLED_APPS``
2) Run ``python manage.py migrate`` to initialize the model
3) Add ``FIELD_LOGGER_SETTINGS`` to your ``settings.py`` file.

.. code:: python

    FIELD_LOGGER_SETTINGS = {
        'ENCODER': 'path.to.your.json.Encoder', # (default: None)
        'DECODER': 'path.to.your.json.Decoder', # (default: None)
        'LOGGING_ENABLED': True, # (default: True)
        'FAIL_SILENTLY': True, # (default: True)
        'LOG_ACTOR': True, # (default: True)
        'LOG_REMOTE_ADDR': True, # (default: True)
        'LOG_DELETIONS': False, # (default: False)
        'MASK_FIELDS': ['password'], # (default: [])
        'MASK_CALLABLE': 'yourapp.masking.your_mask', # (default: None, values logged as '********')
        'LOGGING_APPS': {
            'your_app': {
                'logging_enabled': True, # (default: True)
                'fail_silently': True, # (default: True)
                'log_actor': True, # (default: True)
                'log_remote_addr': True, # (default: True)
                'log_deletions': False, # (default: LOG_DELETIONS)
                'mask_fields': ['field5'], # (default: [])
                'mask_callable': 'yourapp.masking.your_mask', # (default: None)
                'models': {
                    'YourModel': {
                        'logging_enabled': True, # (default: True)
                        'fail_silently': True, # (default: True)
                        'log_actor': True, # (default: True)
                        'log_remote_addr': True, # (default: True)
                        'log_deletions': True, # (default: the app's log_deletions)
                        'fields': ['field1', 'field2'], # or '__all__' (default: [], no field is logged)
                        'exclude_fields': ['field3', 'field4'], # (default: [])
                        'mask_fields': ['field6'], # (default: [])
                        'mask_callable': 'yourapp.masking.your_mask', # (default: None)
                        'callbacks': [
                            lambda instance, fields, logs: print(instance, fields, logs),
                            'yourapp.callbacks.your_function_name'
                        ], # (default: [])
                    },
                },
                'callbacks': [
                    lambda instance, fields, logs: print(instance, fields, logs),
                    'yourapp.callbacks.your_function_name'
                ], # (default: [])
            },
        },
        'CALLBACKS': [
            lambda instance, fields, logs: print(instance, fields, logs),
            'yourapp.callbacks.your_function_name'
        ], # (default: [])
    }

-  ``ENCODER`` and ``DECODER`` are optional. If you want to
   encode/decode your model instance fields, you can specify your
   encoder/decoder classes here. Your encoder/decoder classes must be
   subclasses of ``json.JSONEncoder`` and ``json.JSONDecoder``
   respectively. To keep the default handling of Django field values,
   subclass ``fieldlogger.encoding.Encoder``. Changing them does not
   require a migration.
-  ``LOGGING_ENABLED`` is optional. If you want to disable logging
   globally, you can set this to ``False``. To disable it only for a
   block of code, see `Disabling logging temporarily`_.
-  ``FAIL_SILENTLY`` is optional. With the default ``True``, a failing
   callback is logged, with its traceback, to the
   ``fieldlogger.callbacks`` logger, and the remaining callbacks still
   run. Set it to ``False`` to let the exception propagate.
-  ``LOG_ACTOR`` and ``LOG_REMOTE_ADDR`` are optional. Set them to
   ``False`` not to store the user or the client's IP address (see
   `Recording who made the change`_).
-  ``LOGGING_ENABLED``, ``FAIL_SILENTLY``, ``LOG_ACTOR`` and
   ``LOG_REMOTE_ADDR`` can also be set per app and per model, in
   lowercase (``logging_enabled``, ``fail_silently``, ``log_actor``,
   ``log_remote_addr``). Each one is on unless it is ``False`` in the
   global settings, the app or the model.
-  ``LOG_DELETIONS`` is optional. Set it to ``True`` to log the deletions
   of the logged models (see `Logging deletions`_). Per app and per model
   it is ``log_deletions``, taken from the most specific scope that sets
   it, so an app or a model can turn it on or off for itself.
-  ``MASK_FIELDS`` and ``MASK_CALLABLE`` are optional: fields whose values
   are logged masked, and the function that masks them (see `Masking
   sensitive fields`_). Per app and per model they are ``mask_fields``,
   which add up across scopes like the callbacks, and ``mask_callable``,
   taken from the most specific scope that sets one.
-  ``LOGGING_APPS`` apps to be logged.

   -  ``models`` models to be logged.

      -  ``fields`` the fields to log: a list of field names, or
         ``'__all__'`` to log every field. If it is not specified, no
         field is logged.
      -  ``exclude_fields`` is optional. Fields listed here are never
         logged, even if they are in ``fields``. Combine it with
         ``'fields': '__all__'`` to log every field except a few.

         Only fields with their own database column are loggable:
         reverse relations and database-generated fields
         (``GeneratedField``) are always skipped. Many-to-many fields
         are supported through the ``m2m_changed`` signal (see
         `Many-to-many fields`_).

      -  ``callbacks`` is optional: functions called after the changes of
         an instance of this model are logged. The global ``CALLBACKS``
         and the app's ``callbacks`` run for it too, in that order: global,
         app, model. Each callback is a callable or the dotted path to one
         (e.g. ``'yourapp.callbacks.your_function_name'``), and receives
         three arguments:

         .. code:: python

            # callback as a named function
            def your_callback(instance, fields, logs):
                ...  # your code here

            # callback as a lambda function
            lambda instance, fields, logs: ...  # your code here

         -  ``instance`` the model instance whose changes were logged.
         -  ``fields`` the logged fields of the operation, as a frozenset
            of ``Field`` objects: only the saved ones with
            ``update_fields`` or ``bulk_update()``, and just the
            many-to-many field for its changes.
         -  ``logs`` dict of the logs created for the instance, keyed by
            field name. It is empty when nothing changed: callbacks run for
            every saved instance, while many-to-many changes only run them
            for the instances that got a log.

How it works?
~~~~~~~~~~~~~

-  On startup, reads ``FIELD_LOGGER_SETTINGS`` and resolves, for each
   configured model, the fields to log and the options of its scopes.
-  Connects to the ``pre_save`` and ``post_save`` signals of each logged
   model, to the ``m2m_changed`` signal of each logged many-to-many
   field, and to the ``pre_delete`` and ``post_delete`` signals of the
   models that log deletions. Bulk operations are logged by
   ``FieldLoggerManager`` (see `The FieldLoggerManager`_).
-  Creates one ``FieldLog`` record per changed field: when an instance
   is created (``created=True``), when it is saved with changes, when
   its many-to-many relations change, and, if enabled, when it is
   deleted (``deleted=True``).
-  Gives the logs created together a common ``correlation_id`` (see
   `Grouping the logs of a request`_).
-  The logged values are read back from the database after saving, so
   they are the stored ones: expressions such as ``F('count') + 1`` are
   logged as their result, and values the database rounds or converts
   (e.g. a ``DecimalField``) as stored. This costs one extra query per
   ``save()``, and per batch in bulk operations.
-  Fixture loading (``loaddata``) is a restore, not a change, so it is
   never logged.

Example
~~~~~~~

Given this configuration in your ``settings.py``:

.. code:: python

    FIELD_LOGGER_SETTINGS = {
        'LOGGING_APPS': {
            'drivers': {
                'models': {
                    'Driver': {
                        'fields': ['driver_name']
                    },
                },
            },
        },
    }

and a ``Driver`` model with the fields ``latest_speed``, ``driver_name``
and ``driver_id``:

.. code:: python

    from fieldlogger.models import FieldLog

    driver = Driver.objects.last()
    driver.latest_speed = 5
    driver.save()  # fieldlogger won't create a record since 'latest_speed' was not among the loggable fields

    driver.driver_name = 'John Doe'
    driver.save()  # a record with this driver is created

    driver.driver_name = 'Jane Doe'
    driver.save()  # a record with this driver is created

    instance_id = driver.id
    app_label = driver._meta.app_label
    model_name = driver._meta.model_name

    log = FieldLog.objects.filter(instance_id=instance_id, app_label=app_label, model_name=model_name).last()
    print(log.field, log.old_value, log.new_value)  # prints: driver_name John Doe Jane Doe

Callback example
~~~~~~~~~~~~~~~~

This function, in ``yourapp/callbacks.py``, sets the ``extra_data`` field
of the new log of ``driver_name``:

.. code:: python

    def set_extra_data_for_driver_name(instance, fields, logs):
        log = logs.get('driver_name')
        if log:
            log.extra_data = {
                'name_length': len(log.new_value)
            }
            log.save()

Then you can add this callback function to your configuration like this:

.. code:: python

    FIELD_LOGGER_SETTINGS = {
        'LOGGING_APPS': {
            'drivers': {
                'models': {
                    'Driver': {
                        'fields': ['driver_name'],
                        'callbacks': [
                            'yourapp.callbacks.set_extra_data_for_driver_name'
                        ]
                    },
                },
            },
        },
    }

.. note::

    You can also add lambda functions to your callbacks

The model structure
~~~~~~~~~~~~~~~~~~~

``FieldLog`` stores one record per change to a field of a logged
instance. An example record:

::

    {
        'id': 2,
        'app_label': 'drivers',
        'model_name': 'driver',
        'instance_id': 1,
        'field': 'driver_name',
        'timestamp': datetime.datetime(2024, 1, 16, 9, 1, 14, 619568, tzinfo=<UTC>), # set when the log is created
        'old_value': 'John Doe',
        'new_value': 'Jane Doe',
        'extra_data': {}, # this is a JSONField, you can store any extra data here using callbacks or by overriding it directly
        'created': False, # this is a boolean field, if it is True, it means that instance is a newly created instance
        'deleted': False, # True if the instance was deleted, see "Logging deletions"
        'actor_id': '7', # who made the change, see "Recording who made the change" (default: None)
        'actor_username': 'admin', # (default: None)
        'remote_addr': '127.0.0.1', # (default: None)
        'correlation_id': '1b4e28ba-2fa1-4d3b-a3f5-ef19b5a7633b', # see "Grouping the logs of a request"
        'masked': False, # True if the values were masked, see "Masking sensitive fields"
    }

Additionally, ``FieldLog`` model provides the following properties:

-  ``model``: returns the model class of the instance that is
   being logged.
-  ``instance``: returns the instance that is being logged, or raises
   its model's ``DoesNotExist`` if it was deleted.
-  ``previous_log``: returns the previous log of the same field of the
   same instance, if any.
-  ``actor``: returns the user who made the change, if known and not
   deleted since.

Values are stored as JSON and converted back to Python objects when a
log is loaded:

-  Binary values are stored base64-encoded, so any binary content is
   supported.
-  Foreign key values are resolved back to model instances lazily (no
   query until the value is accessed). If the related instance was
   deleted, an unsaved instance carrying only the primary key is
   returned, so reading old logs never fails.
-  Models with a composite primary key (Django >= 5.2) are not
   supported.

The FieldLoggerMixin
~~~~~~~~~~~~~~~~~~~~

Add ``FieldLoggerMixin`` to a logged model to get this property:

-  ``fieldlog_set``: the logs of the instance. ``FieldLog`` has no
   foreign key to the logged models, so this property plays the part of
   a reverse relation, returning a new QuerySet on every access.

   .. code:: python

        driver = Driver.objects.last()
        logs = driver.fieldlog_set.all()

The FieldLoggerManager
~~~~~~~~~~~~~~~~~~~~~~

Django signals are not fired on bulk operations, so changes made through
``bulk_create`` and ``bulk_update`` are not logged by default. This
package provides a manager called ``FieldLoggerManager`` that overrides
both methods to log field changes as well:

.. code:: python

    from django.db import models

    from fieldlogger.managers import FieldLoggerManager

    class Driver(models.Model):
        # ...

        objects = FieldLoggerManager()

The methods are defined on ``FieldLoggerQuerySet``, the QuerySet the
manager returns, so they are also logged after chained calls such as
``Driver.objects.using('other').bulk_create(...)`` or
``Driver.objects.filter(...).bulk_update(...)``, and through their
async variants ``abulk_create`` and ``abulk_update`` (available on the
manager from Django 4.1, on the QuerySet on every version).

Your own QuerySet keeps logging:
``FieldLoggerManager.from_queryset(YourQuerySet)``, and a
``FieldLoggerManager`` subclass whose ``get_queryset()`` returns another
QuerySet, both combine it with ``FieldLoggerQuerySet``. You can
also subclass ``FieldLoggerQuerySet`` and use ``YourQuerySet.as_manager()``.

All of them accept two extra keyword arguments:

-  ``log_fields`` set it to ``False`` to skip logging for that call
   (default: ``True``). To skip it for every operation in a block, see
   `Disabling logging temporarily`_.
-  ``run_callbacks`` set it to ``False`` to skip the configured
   callbacks for that call (default: ``True``).

.. code:: python

    Driver.objects.bulk_create([Driver(driver_name='John Doe')])
    Driver.objects.bulk_update(drivers, ['driver_name'], run_callbacks=False)

With ``bulk_create(update_conflicts=True)``, objects that update an
existing row are logged as changes of the ``update_fields`` instead of
as creations.

``QuerySet.update()`` does not fire signals and is not logged.

Many-to-many fields
~~~~~~~~~~~~~~~~~~~

Many-to-many changes do not go through ``save()``, so they are logged
from the ``m2m_changed`` signal instead. Any loggable many-to-many
field gets one log per change, holding the sorted lists of related
primary keys before and after. Given a ``cars`` field on ``Driver``
with ``'fields': ['cars']`` in its configuration:

.. code:: python

    class Driver(FieldLoggerMixin, models.Model):
        cars = models.ManyToManyField(Car)

    driver.cars.add(car1, car2)
    log = driver.fieldlog_set.get(field='cars')
    print(log.old_value, log.new_value)  # prints: [] [1, 2]

Changes made from the reverse side of the relation (the
``car.driver_set`` accessor) are logged too, but always on the model
that declares the field (``Driver`` here); ``Car`` gets no logs. Every
driver affected by the change gets its own log:

.. code:: python

    car3.driver_set.add(driver, other_driver)
    log = driver.fieldlog_set.filter(field='cars').last()
    print(log.old_value, log.new_value)  # prints: [1, 2] [1, 2, 3]

    car3.driver_set.clear()  # logs [1, 2, 3] -> [1, 2] on driver and [3] -> [] on other_driver

-  ``add``, ``remove``, ``set`` and ``clear`` are logged, from both
   sides of the relation.
-  Changes made directly on an explicit ``through`` model (e.g.
   ``Membership.objects.create(...)``) do not fire ``m2m_changed``, so
   they are not logged; this mirrors Django's own behavior.

Logging deletions
~~~~~~~~~~~~~~~~~

Deletions are not logged by default. To log them, set ``log_deletions``
to ``True`` in the configuration of a model or an app, or
``LOG_DELETIONS`` globally:

.. code:: python

    FIELD_LOGGER_SETTINGS = {
        'LOGGING_APPS': {
            'drivers': {
                'models': {
                    'Driver': {
                        'fields': '__all__',
                        'log_deletions': True,
                    },
                },
            },
        },
    }

    driver_id = driver.pk
    driver.delete()

    log = FieldLog.objects.get(
        app_label='drivers', model_name='driver', instance_id=driver_id,
        field='driver_name', deleted=True,
    )
    print(log.old_value, log.new_value)  # prints: Jane Doe None

A deletion is logged like a creation, the other way around: one log per
logged field that had a value, from its last value to ``None``, with
``deleted=True``. The logs thus keep the final state of the instance,
even if earlier changes were not logged.

-  The values are read from the database just before the deletion, as
   for a save: ``instance.delete()`` costs one extra query. The objects
   Django loads to delete them, in ``QuerySet.delete()`` or a cascade,
   are used as loaded (on Django 4.0, which does not tell them apart,
   they are read too).
-  ``QuerySet.delete()`` and cascades are logged, since Django sends the
   deletion signals for every object. To send them, Django loads every
   object of a model that logs deletions before deleting it, instead of
   deleting the rows with a single query: leave it off for models whose
   large bulk deletions you do not need to log.
-  Many-to-many fields are not logged on deletion: Django deletes the
   rows of the relation without the ``m2m_changed`` signal. Their last
   logged state is in the latest log of the field.
-  The logs record who deleted the instance and the correlation ID, the
   fields in ``mask_fields`` are masked, and inside
   ``disable_logging()`` nothing is logged.
-  Callbacks run for the deleted instances that got a log, which still
   have their primary key; ``log.deleted`` tells deletions apart.
   ``log.instance`` raises ``DoesNotExist`` for them.
-  The most specific scope that sets ``log_deletions`` applies: with
   ``LOG_DELETIONS`` on, a model can turn it off with
   ``'log_deletions': False``.

Masking sensitive fields
~~~~~~~~~~~~~~~~~~~~~~~~

To record that a sensitive field changed without storing its values, add
it to ``mask_fields``. Its logs still show when the field changed and
who changed it, but ``old_value`` and ``new_value`` hold a mask instead
of the values, and ``log.masked`` is ``True``:

.. code:: python

    FIELD_LOGGER_SETTINGS = {
        'MASK_FIELDS': ['password'],  # in every logged model
        'LOGGING_APPS': {
            'drivers': {
                'models': {
                    'Driver': {
                        'fields': '__all__',
                        'mask_fields': ['license_number'],
                    },
                },
            },
        },
    }

    log = driver.fieldlog_set.filter(field='license_number').last()
    print(log.old_value, log.new_value, log.masked)  # prints: ******** ******** True

-  The mask is ``'********'`` for any value, so it reveals neither part of
   the value nor its length. An empty value (``None``) is logged as
   ``None``, so you can still see when the field was set or cleared.
-  Changes are detected on the real values, before masking.
-  Masked values are not converted back when a log is loaded, since they
   are not values of the field, and callbacks receive the logs already
   masked.
-  Many-to-many fields can be masked too: both lists are replaced by the
   mask.
-  The global ``MASK_FIELDS`` and the ``mask_fields`` of the app and of
   the model add up.
-  Values are masked when the log is created: changing the configuration
   later does not alter existing logs.

To log something else, such as the last digits, set ``mask_callable`` (a
function or its dotted path) in the model or app configuration, or
``MASK_CALLABLE`` globally; the most specific one applies. It receives
the real value and returns what is logged, which must be serializable to
JSON:

.. code:: python

    def last_four(value):
        return '****' + str(value)[-4:]

Recording who made the change
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Add ``FieldLoggerMiddleware`` after Django's ``AuthenticationMiddleware``
to record, in every log created while handling a request, the user and
the client's IP address:

.. code:: python

    MIDDLEWARE = [
        # ...
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'fieldlogger.middleware.FieldLoggerMiddleware',
    ]

The logs then get:

-  ``actor_id``: the primary key of the user, as text, like
   ``instance_id`` in the database. Filter with
   ``FieldLog.objects.filter(actor_id=user.pk)``, and compare it with
   ``str(user.pk)`` in Python.
-  ``actor_username``: the user's ``get_username()`` at the time of the
   change.
-  ``remote_addr``: the client's IP address.

Values that are not known are ``None``, except ``actor_id`` and
``actor_username`` on Oracle, which reads empty text columns back as
``''``: test them with ``if log.actor_id:``.

There is no foreign key to the user model, so both ``actor_id`` and
``actor_username`` stay when the user is renamed or deleted;
``log.actor`` loads the user, or returns ``None`` if it was deleted.
Anonymous requests record only the IP address, and ``request.user`` is
only loaded when a log is created. The middleware works with both WSGI
and ASGI.

Code that does not run in a request, such as Celery tasks, management
commands or scripts, can set the user with ``set_actor()``, which can
also decorate a function:

.. code:: python

    from fieldlogger import set_actor

    with set_actor(user):
        driver.save()  # logged with this user

To keep the user or the IP address out of the logs of some apps or
models, set ``log_actor`` or ``log_remote_addr`` to ``False`` in their
configuration, or ``LOG_ACTOR`` or ``LOG_REMOTE_ADDR`` to turn them off
everywhere. Without ``log_actor``, ``request.user`` is not even loaded
for those logs:

.. code:: python

    FIELD_LOGGER_SETTINGS = {
        'LOGGING_APPS': {
            'hr': {
                'log_actor': False,  # no app model records the user
                'models': {...},
            },
            'drivers': {
                'models': {
                    'Driver': {
                        'fields': '__all__',
                        'log_remote_addr': False,  # only this model skips the IP
                    },
                },
            },
        },
    }

The IP address is personal data. It comes from ``REMOTE_ADDR``, which
behind a reverse proxy is the proxy's address. Override
``get_remote_addr()`` to read the header your proxy sets instead; do
not read ``X-Forwarded-For`` unless your proxy sets it, since clients
can send it with any value. Values that are not valid IP addresses are
not stored.

.. code:: python

    from fieldlogger.middleware import FieldLoggerMiddleware

    class ProxyFieldLoggerMiddleware(FieldLoggerMiddleware):
        def get_remote_addr(self, request):
            return request.headers.get('X-Real-IP')

``django.contrib.auth`` is not required: without it, the middleware
records only the IP address.

The middleware also gives the logs of each request a common correlation
ID (see `Grouping the logs of a request`_).

Grouping the logs of a request
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each log has a ``correlation_id`` shared with the logs created along
with it:

-  In a request handled by ``FieldLoggerMiddleware``, all the logs of the
   request share a new random ID (a UUID).
-  Inside a ``set_correlation_id()`` block, the logs get the ID of the
   block: the one you pass, such as the ID of a Celery task, or a new
   random one.
-  Elsewhere, the logs of each operation share an ID: a ``save()``, a
   bulk operation, a many-to-many change, or the deletion of an object.

.. code:: python

    from fieldlogger import set_correlation_id

    with set_correlation_id(task_id) as correlation_id:
        import_drivers()

    logs = FieldLog.objects.filter(correlation_id=correlation_id)

The column is indexed, and IDs longer than 255 characters are
truncated. ``set_correlation_id()`` can also decorate a function, with a
new ID on every call, and blocks can be nested; the innermost one
applies.

To use the ID that identifies the request elsewhere, such as one set by
your proxy or by a request-ID library, override ``get_correlation_id()``
in the middleware; when it returns no value, a new ID is generated. As
with the IP address, only read a header your proxy sets, since clients
can send any value:

.. code:: python

    class RequestIdFieldLoggerMiddleware(FieldLoggerMiddleware):
        def get_correlation_id(self, request):
            return request.headers.get('X-Request-ID')

Disabling logging temporarily
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``disable_logging()`` turns logging off inside a ``with`` block, for
example while importing data:

.. code:: python

    from fieldlogger import disable_logging

    with disable_logging():
        for driver in drivers:
            driver.save()  # not logged
        Driver.objects.bulk_create(new_drivers)  # not logged

Inside the block, ``save()``, many-to-many changes, deletions and the
bulk operations of ``FieldLoggerManager`` and its querysets (including
``abulk_create`` and ``abulk_update``) create no logs and run no
callbacks, and the queries that read the previous values are skipped.
Changes made inside the block are not logged later either: the next log
of a field starts from the value stored at that point.

The state is kept in a ``contextvars.ContextVar``, so it only affects
the current thread or async task: other requests keep logging. Blocks
can be nested, and it can also decorate a function:

.. code:: python

    @disable_logging()
    def import_drivers(rows):
        ...

In async code, use it as a ``with`` block inside the coroutine.

License
~~~~~~~

Copyright (c) 2024 Sergio Rodríguez

Released under the MIT License. See the `LICENSE
<https://github.com/Nibblex/django-field-logger/blob/main/LICENSE>`_
file for details.
