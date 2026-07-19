import django
from django.db import models

from fieldlogger.managers import FieldLoggerManager
from fieldlogger.mixins import FieldLoggerMixin


class TestingFieldsMixin(models.Model):
    test_big_integer_field = models.BigIntegerField(null=True)
    test_binary_field = models.BinaryField(null=True)
    test_binary_memoryview_field = models.BinaryField(null=True)
    test_boolean_field = models.BooleanField(null=True)
    test_char_field = models.CharField(max_length=255, null=True)
    test_date_field = models.DateField(null=True)
    test_datetime_field = models.DateTimeField(null=True)
    test_decimal_field = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    test_duration_field = models.DurationField(null=True)
    test_email_field = models.EmailField(null=True)
    test_file_field = models.FileField(upload_to="test_file_field", null=True)
    test_file_path_field = models.FilePathField(path="tests/testapp", null=True)
    test_float_field = models.FloatField(null=True)
    test_generic_ip_address_field = models.GenericIPAddressField(null=True)
    test_image_field = models.ImageField(upload_to="test_image_field", null=True)
    test_integer_field = models.IntegerField(null=True)
    test_json_field = models.JSONField(null=True)
    test_positive_big_integer_field = models.PositiveBigIntegerField(null=True)
    test_positive_integer_field = models.PositiveIntegerField(null=True)
    test_positive_small_integer_field = models.PositiveSmallIntegerField(null=True)
    test_slug_field = models.SlugField(null=True)
    test_small_integer_field = models.SmallIntegerField(null=True)
    test_text_field = models.TextField(null=True)
    test_time_field = models.TimeField(null=True)
    test_url_field = models.URLField(null=True)
    test_uuid_field = models.UUIDField(null=True)

    __test__ = False

    class Meta:
        abstract = True


class TestModelRelated2(FieldLoggerMixin, TestingFieldsMixin):
    test_related_field3 = models.ForeignKey(
        "TestModel", on_delete=models.CASCADE, null=True
    )


class TestModelRelated(FieldLoggerMixin, TestingFieldsMixin):
    test_related_field2 = models.ForeignKey(
        TestModelRelated2, on_delete=models.CASCADE, null=True
    )


class TestModel(FieldLoggerMixin, TestingFieldsMixin):
    test_related_field = models.ForeignKey(
        TestModelRelated, on_delete=models.CASCADE, null=True
    )
    test_one_to_one_field = models.OneToOneField(
        TestModelRelated2, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    test_many_to_many_field = models.ManyToManyField(
        TestModelRelated2, related_name="test_reverse_m2m"
    )
    test_unique_field = models.CharField(max_length=32, unique=True, null=True)

    objects = FieldLoggerManager()


if django.VERSION >= (5, 0):
    TestModel.add_to_class(
        "test_generated_field",
        models.GeneratedField(
            expression=models.F("test_integer_field") + 1,
            output_field=models.IntegerField(),
            db_persist=True,
            null=True,
        ),
    )
