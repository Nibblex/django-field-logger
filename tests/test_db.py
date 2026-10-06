import pytest

from fieldlogger import db
from fieldlogger.models import FieldLog

from .testapp.models import SoftDeleteModel


@pytest.mark.django_db(transaction=True)
def test_set_primary_keys_assigns_sequential_pks():
    logs = [
        FieldLog(app_label="testapp", model_name="testmodel", field="f", instance_id=i)
        for i in range(3)
    ]

    db.set_primary_keys(logs, FieldLog)
    max_pk = FieldLog.objects.count()
    assert [log.pk for log in logs] == [max_pk + 1, max_pk + 2, max_pk + 3]


@pytest.mark.django_db(transaction=True)
def test_set_primary_keys_keeps_preset_pks():
    logs = [
        FieldLog(app_label="testapp", model_name="testmodel", field="f"),
        FieldLog(app_label="testapp", model_name="testmodel", field="f", pk=999),
    ]

    db.set_primary_keys(logs, FieldLog)
    assert [log.pk for log in logs] == [1, 999]


@pytest.mark.django_db(transaction=True)
def test_set_primary_keys_counts_rows_hidden_by_default_manager():
    """The next pk is computed over every row, including those that the
    model's default manager filters out, and works on models without an
    ``objects`` manager."""
    SoftDeleteModel.items.create()
    hidden = SoftDeleteModel.items.create(deleted=True)
    assert SoftDeleteModel.items.count() == 1

    objs = [SoftDeleteModel()]
    db.set_primary_keys(objs, SoftDeleteModel)
    assert objs[0].pk == hidden.pk + 1
