# Django Field Logger

### Quick Description
A python package which logs each change made to a Django model instance.

### How to set up?
1) Add ```fieldlogger``` to your ```INSTALLED_APPS```
2) Run ```python manage.py migrate``` to initialize the model
3) Add ```FIELD_LOGGER_SETTINGS``` to your settings.py file.

```python
FIELD_LOGGER_SETTINGS={
    'ENCODER': 'path.to.your.json.Encoder', # (default: None)
    'DECODER': 'path.to.your.json.Decoder', # (default: None)
    'LOGGING_ENABLED': True, # (default: True)
    'LOGGING_APPS': {
        'your_app': {
            'logging_enabled': True, # (default: True)
            'models': {
                'YourModel': {
                    'logging_enabled': True, # (default: True)
                    'fields': ['field1', 'field2'], # (default: [])
                    'exclude_fields': ['field3', 'field4'], # (default: [])
                    'callbacks': [
                        lambda instance, fields, logs: print(instance, fields, logs),
                        'yourapp.app.callbacks.your_function_name'
                    ], # (default: [])
                },
            },
            'callbacks': [
                lambda instances, fields, logs: print(instances, fields, logs),
                'yourapp.app.callbacks.your_function_name'
            ], # (default: [])
        },
    },
    'CALLBACKS': [
        lambda instance, fields, logs: print(instance, fields, logs),
        'yourapp.app.callbacks.your_function_name'
    ], # (default: [])
}

```

- ```ENCODER``` and ```DECODER``` are optional. If you want to encode/decode your model instance fields, you can specify your encoder/decoder
    classes here. Your encoder/decoder classes must be subclasses of ```json.JSONEncoder``` and ```json.JSONDecoder``` respectively.
- ```LOGGING_ENABLED``` is optional. If you want to disable logging globally, you can set this to ```False```.
- ```LOGGING_APPS``` apps to be logged.
    - ```models``` models to be logged.
        - ```fields``` is optional. If you want to log only specific fields, you can specify them here.
        - ```exclude_fields``` is optional. If ```fields``` is not specified, all fields in the model will be logged except the ones specified here.
        - ```callbacks``` is optional. If you want to add a callback function to be called after logging all models in all apps, you can add it here.
            Callback functions must be callable objects. You can optionally specify a callback function path in your configuration.
            The best practice is to place your callback function in yourapp/callbacks.py
            Callback functions must have the following signature:
            ```python
            def callback(instance, fields, logs):
                pass
            ```

            - ```instance``` the model instance that is being logged.
            - ```fields``` list of fields that are being logged.
            - ```logs``` dict of logs that are being created. The key is the field name and the value is the ```FieldLog``` instance.


### How it works?

- Obtains the ```FIELD_LOGGER_SETTINGS``` from your respective settings file based
  on your environment.
- Initializes ```LOGGING_APPS``` with the relative project paths of your
  models based on your configuration variable.
- Binds to pre_save signal of each loggable model
- For each field specified in the configuration variable, creates a record in
  the ```FieldLog``` model in each instance update.

### Example

This section serves as a small example to demonstrate this package.

Supposing you have this configuration in your settings.py file:

```python
FIELD_LOGGER_SETTINGS={
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
```

Supposing you have a model called ```Driver``` and fields called ```latest_speed``` and ```driver_name``` and ```driver_id```:
    
```python
    driver = Driver.objects.last()
    driver.latest_speed = 5
    driver.save()  # fieldlogger won't create a record since 'latest_speed' was not among the loggable fields

    driver.driver_name = 'John Doe'
    driver.save()  # a record with this driver is created

    driver.driver_name = 'Jane Doe'
    driver.save()  # a record with this driver is created

    instance_id = driver.id
    app_label = driver._meta.app_label
    model = driver._meta.model_name

    log = FieldLog.objects.filter(instance_id=instance_id, app_label=app_label, table_name=model).last()
    print(log.field, log.old_value, log.new_value)  # prints: driver_name John Doe Jane Doe
```

### Callback example

Supposing you have this function in yourapp/callbacks.py which sets the ```extra_data``` field of the ```FieldLog``` model:

```python
def set_extra_data_for_driver_name(instance, fields, logs):
    log = logs.get('driver_name')
    if log:
        log.extra_data = {
            'name_length': len(log.new_value)
        }
        log.save()
```

You can add this function to your configuration like this:

```python
FIELD_LOGGER_SETTINGS={
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
```

### The model structure

This package provides you a django model which is called ```FieldLog```; which tracks each change to a model 
instance specified in your configuration mapping. An example record is as
follows:

```
{
 'id': 2,
 'app_label': 'drivers',
 'model': 'driver',
 'instance_id': 1,
 'field': 'latest_speed',
 'timestamp': datetime.datetime(2024, 1, 16, 9, 1, 14, 619568, tzinfo=<UTC>),
 'old_value': 'John Doe',
 'new_value': 'Jane Doe',
 'extra_data': {}, # this is a JSONField, you can store any extra data here using callbacks or by overriding it directly
 'created': False, # this is a boolean field, if it is True, it means that instance is a newly created instance
}

```

Additionally, ```FieldLog``` model provides the following properties:

- ```model_class```: returns the model class of the instance that is being logged.
- ```instance```: returns the instance that is being logged.
- ```previous_log```: returns the previous log of the instance that is being logged.


### The FieldLoggerMixin

This package provides you a mixin class which is called ```FieldLoggerMixin```.
This mixin class provides you the following property:

- ```fieldlog_set``` returns the ```FieldLog``` queryset of the instance that is being logged.
