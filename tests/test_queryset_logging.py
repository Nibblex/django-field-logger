import json

import pytest
from django.db import connection

from fieldlogger.models import FieldLog

from .testapp.models import TestModel


@pytest.mark.django_db
class TestQuerySetFieldLogging:
    """
    Tests that the logging model (FieldLog) correctly serializes QuerySet
    values through its custom JSON encoder when recording field changes.
    """

    def test_queryset_new_value_stored_as_pk_list(self):
        instances = [TestModel.objects.create() for _ in range(3)]
        queryset = TestModel.objects.filter(pk__in=[i.pk for i in instances])
        expected_pks = sorted(i.pk for i in instances)

        new_value_field = FieldLog._meta.get_field("new_value")
        serialized = new_value_field.get_db_prep_save(queryset, connection=connection)

        assert sorted(json.loads(serialized)) == expected_pks

    def test_empty_queryset_new_value_stored_as_empty_list(self):
        new_value_field = FieldLog._meta.get_field("new_value")
        serialized = new_value_field.get_db_prep_save(
            TestModel.objects.none(), connection=connection
        )

        assert json.loads(serialized) == []
