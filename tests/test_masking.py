"""Masking the logged values of sensitive fields (mask_fields)."""

from decimal import Decimal

import pytest

from fieldlogger.masking import MASK
from fieldlogger.models import FieldLog

from .helpers import set_config
from .testapp.models import TestModel, TestModelRelated, TestModelRelated2


def last_two(value):
    """A custom mask, set by dotted path in the tests below."""
    return "****" + str(value)[-2:]


def logs_of(instance, field):
    """(created, old_value, new_value, masked) of each log of ``field``,
    loaded from the database."""
    return [
        (log.created, log.old_value, log.new_value, log.masked)
        for log in instance.fieldlog_set.filter(field=field).order_by("pk")
    ]


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("restore_settings")
class TestMaskFields:
    def test_values_are_logged_masked(self):
        set_config({"mask_fields": ["test_char_field"]}, "testmodel")
        instance = TestModel.objects.create(test_char_field="secret")
        instance.test_char_field = "other"
        instance.save()

        assert logs_of(instance, "test_char_field") == [
            (True, None, MASK, True),
            (False, MASK, MASK, True),
        ]

    def test_other_fields_are_not_masked(self):
        set_config({"mask_fields": ["test_char_field"]}, "testmodel")
        instance = TestModel.objects.create(
            test_char_field="secret", test_integer_field=1
        )

        assert logs_of(instance, "test_integer_field") == [(True, None, 1, False)]

    def test_changes_are_detected_on_the_real_values(self):
        set_config({"mask_fields": ["test_char_field"]}, "testmodel")
        instance = TestModel.objects.create(test_char_field="secret")
        instance.save()  # Nothing changed.
        instance.test_char_field = "other"
        instance.save()  # Masked the same, but changed.

        assert len(logs_of(instance, "test_char_field")) == 2

    def test_no_value_is_not_masked(self):
        set_config({"mask_fields": ["test_char_field"]}, "testmodel")
        instance = TestModel.objects.create(test_char_field="secret")
        instance.test_char_field = None
        instance.save()

        assert logs_of(instance, "test_char_field")[-1] == (False, MASK, None, True)

    def test_masked_values_are_not_converted_on_load(self):
        """A Decimal or a foreign key would fail to convert from the mask."""
        set_config(
            {"mask_fields": ["test_decimal_field", "test_related_field"]}, "testmodel"
        )
        instance = TestModel.objects.create(
            test_decimal_field=Decimal("3.14"),
            test_related_field=TestModelRelated.objects.create(),
        )

        assert logs_of(instance, "test_decimal_field") == [(True, None, MASK, True)]
        assert logs_of(instance, "test_related_field") == [(True, None, MASK, True)]

    def test_m2m_changes_are_masked(self):
        set_config({"mask_fields": ["test_many_to_many_field"]}, "testmodel")
        instance = TestModel.objects.create()
        instance.test_many_to_many_field.add(TestModelRelated2.objects.create())

        assert logs_of(instance, "test_many_to_many_field") == [
            (False, MASK, MASK, True)
        ]

    def test_bulk_operations_are_masked(self):
        set_config({"mask_fields": ["test_char_field"]}, "testmodel")
        (instance,) = TestModel.objects.bulk_create([TestModel(test_char_field="a")])
        instance.test_char_field = "b"
        TestModel.objects.bulk_update([instance], ["test_char_field"])

        assert logs_of(instance, "test_char_field") == [
            (True, None, MASK, True),
            (False, MASK, MASK, True),
        ]

    @pytest.mark.parametrize("scope", ["global", "testapp", "testmodel"])
    def test_any_scope_can_mask(self, scope):
        set_config({"mask_fields": ["test_char_field"]}, scope)
        instance = TestModel.objects.create(test_char_field="secret")

        assert logs_of(instance, "test_char_field") == [(True, None, MASK, True)]

    def test_the_fields_of_every_scope_are_masked(self):
        set_config({"mask_fields": ["test_char_field"]}, "global")
        set_config({"mask_fields": ["test_integer_field"]}, "testmodel")
        instance = TestModel.objects.create(test_char_field="a", test_integer_field=1)

        assert logs_of(instance, "test_char_field")[0][3]
        assert logs_of(instance, "test_integer_field")[0][3]

    def test_excluded_fields_are_not_logged(self):
        set_config(
            {"mask_fields": ["test_char_field"], "exclude_fields": ["test_char_field"]},
            "testmodel",
        )
        instance = TestModel.objects.create(test_char_field="secret")

        assert logs_of(instance, "test_char_field") == []

    def test_callbacks_receive_masked_values(self):
        seen = []

        def callback(instance, fields, logs):
            seen.extend((log.new_value, log.masked) for log in logs.values())

        set_config(
            {"mask_fields": ["test_char_field"], "callbacks": [callback]}, "testmodel"
        )
        TestModel.objects.create(test_char_field="secret")

        assert seen == [(MASK, True)]

    def test_a_deferred_masked_column_skips_the_conversion(
        self, django_assert_num_queries
    ):
        """Without ``masked`` the values cannot be converted safely; they are
        left as JSON instead of fetching the column for every row."""
        instance = TestModel.objects.create(test_decimal_field=Decimal("3.14"))

        with django_assert_num_queries(1):
            log = FieldLog.objects.defer("masked").get(
                instance_id=instance.pk, field="test_decimal_field"
            )

        assert log.new_value == pytest.approx(3.14)
        assert not isinstance(log.new_value, Decimal)


@pytest.mark.django_db(transaction=True)
@pytest.mark.usefixtures("restore_settings")
class TestMaskCallable:
    @pytest.mark.parametrize(
        "mask", [last_two, "tests.test_masking.last_two"], ids=["callable", "path"]
    )
    def test_a_custom_mask_replaces_the_default(self, mask):
        set_config(
            {"mask_fields": ["test_char_field"], "mask_callable": mask}, "testmodel"
        )
        instance = TestModel.objects.create(test_char_field="secret")

        assert logs_of(instance, "test_char_field") == [(True, None, "****et", True)]

    def test_the_most_specific_mask_applies(self):
        set_config({"mask_callable": lambda value: "global"}, "global")
        set_config({"mask_callable": lambda value: "app"}, "testapp")
        set_config({"mask_fields": ["test_char_field"]}, "testmodel")
        app = TestModel.objects.create(test_char_field="a")

        set_config({"mask_callable": last_two}, "testmodel")
        model = TestModel.objects.create(test_char_field="secret")

        assert logs_of(app, "test_char_field")[0][2] == "app"
        assert logs_of(model, "test_char_field")[0][2] == "****et"

    def test_the_global_mask_applies_without_others(self):
        set_config({"mask_callable": lambda value: "global"}, "global")
        set_config({"mask_fields": ["test_char_field"]}, "testmodel")
        instance = TestModel.objects.create(test_char_field="secret")

        assert logs_of(instance, "test_char_field")[0][2] == "global"
