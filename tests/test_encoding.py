import json

import pytest

from fieldlogger.encoding import Encoder

from .testapp.models import TestModel


@pytest.mark.django_db
class TestEncoderQuerySet:
    def test_queryset_encoded_as_pk_list(self):
        instances = [TestModel.objects.create() for _ in range(3)]
        queryset = TestModel.objects.filter(pk__in=[i.pk for i in instances])
        expected_pks = list(queryset.values_list("pk", flat=True))

        result = json.loads(json.dumps(queryset, cls=Encoder))

        assert result == expected_pks

    def test_empty_queryset_encoded_as_empty_list(self):
        result = json.loads(json.dumps(TestModel.objects.none(), cls=Encoder))

        assert result == []
