import pytest

from fieldlogger.utils import getrmodel, hasrmodel

from .testapp.models import TestModel, TestModelRelated2


@pytest.mark.parametrize(
    "field", [field for field in TestModel._meta.fields if field.name != "id"]
)
class TestRelatedModelOfDirectFields:
    def test_getrmodel(self, field):
        assert getrmodel(TestModel, field.name) == field.related_model

    def test_hasrmodel(self, field):
        assert hasrmodel(TestModel, field.name) == field.is_relation


@pytest.mark.parametrize("sep", [".", "__"])
@pytest.mark.parametrize(
    "related_field",
    [
        (["test_related_field", "test_char_field"], None),
        (["test_related_field", "test_related_field2"], TestModelRelated2),
        (
            ["test_related_field", "test_related_field2", "test_char_field"],
            None,
        ),
        (
            ["test_related_field", "test_related_field2", "test_related_field3"],
            TestModel,
        ),
        (
            [
                "test_related_field",
                "test_related_field2",
                "test_related_field3",
                "test_char_field",
            ],
            None,
        ),
    ],
)
class TestRelatedModelOfFieldPaths:
    def test_getrmodel(self, sep, related_field):
        rattr, expected_cls = related_field
        assert getrmodel(TestModel, sep.join(rattr)) == expected_cls
        assert (
            expected_cls
            == getattr(
                getrmodel(TestModel, sep.join(rattr[:-1])),
                rattr[-1],
            ).field.related_model
        )

    def test_hasrmodel(self, sep, related_field):
        rattr, expected_cls = related_field
        assert hasrmodel(TestModel, sep.join(rattr)) == bool(expected_cls)


@pytest.mark.parametrize("sep", [".", "__"])
@pytest.mark.parametrize(
    "related_field",
    [
        [""],
        ["objects"],
        ["non_existent_field"],
        ["test_related_field", "non_existent_field"],
        ["test_related_field", "test_related_field2", "non_existent_field"],
    ],
)
class TestRelatedModelOfUnknownFields:
    def test_getrmodel(self, sep, related_field):
        assert getrmodel(TestModel, sep.join(related_field)) is None

    def test_hasrmodel(self, sep, related_field):
        assert not hasrmodel(TestModel, sep.join(related_field))
