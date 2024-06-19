import pytest

from fieldlogger.utils import getrmodel, hasrmodel, rgetattr, rhasattr, rsetattr

from .helpers import CREATE_FORM, UPDATE_FORM
from .testapp.models import TestModel, TestModelRelated, TestModelRelated2


@pytest.fixture
def test_instance():
    related_instance3 = TestModel.objects.create()
    related_instance2 = TestModelRelated2.objects.create(
        test_char_field="test", test_related_field3=related_instance3
    )
    related_instance = TestModelRelated.objects.create(
        test_char_field="test", test_related_field2=related_instance2
    )
    return TestModel.objects.create(**CREATE_FORM, test_related_field=related_instance)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "field", [field for field in TestModel._meta.fields if field.name != "id"]
)
class TestUtilsOnDirectFields:
    def test_rgetattr(self, test_instance, field):
        assert rgetattr(test_instance, field.name) == getattr(test_instance, field.name)

    def test_rhasattr(self, test_instance, field):
        assert rhasattr(test_instance, field.name)

    def test_rsetattr(self, test_instance, field):
        if not field.is_relation:
            rsetattr(test_instance, field.name, UPDATE_FORM[field.name])
            assert getattr(test_instance, field.name) == UPDATE_FORM[field.name]

    def test_getrmodel(self, field):
        assert getrmodel(TestModel, field.name) == field.related_model

    def test_hasrmodel(self, field):
        assert hasrmodel(TestModel, field.name) == field.is_relation


@pytest.mark.django_db
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
class TestUtilsOnRelatedFields:
    def test_rgetattr(self, test_instance, sep, related_field):
        rattr, _ = related_field
        assert rgetattr(test_instance, sep.join(rattr)) == getattr(
            rgetattr(test_instance, sep.join(rattr[:-1])), rattr[-1]
        )

    def test_rhasattr(self, test_instance, sep, related_field):
        rattr, _ = related_field
        assert rhasattr(test_instance, sep.join(rattr))

    def test_rsetattr(self, test_instance, sep, related_field):
        rattr, _ = related_field
        if rattr[-1] == "test_char_field":
            rsetattr(test_instance, sep.join(rattr), "test2")
            assert rgetattr(test_instance, sep.join(rattr)) == "test2"

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


@pytest.mark.django_db
@pytest.mark.parametrize("sep", [".", "__"])
@pytest.mark.parametrize(
    "related_field",
    [
        [""],
        ["non_existent_field"],
        ["test_related_field", "non_existent_field"],
        ["test_related_field", "test_related_field2", "non_existent_field"],
    ],
)
class TestUtilsOnNonExistentFields:
    def test_rgetattr(self, test_instance, sep, related_field):
        with pytest.raises(AttributeError):
            assert rgetattr(test_instance, sep.join(related_field))

    def test_rhasattr(self, test_instance, sep, related_field):
        assert not rhasattr(test_instance, sep.join(related_field))

    def test_rsetattr(self, test_instance, sep, related_field):
        rsetattr(test_instance, sep.join(related_field), "test")
        assert rgetattr(test_instance, sep.join(related_field)) == "test"

    def test_getrmodel(self, sep, related_field):
        assert getrmodel(TestModel, sep.join(related_field)) is None

    def test_hasrmodel(self, sep, related_field):
        assert not hasrmodel(TestModel, sep.join(related_field))
