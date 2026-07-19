import pytest

from fieldlogger import fieldlogger, signals

from .testapp.models import TestModel, TestModelRelated, TestModelRelated2

CALLBACKS_EXTRA_DATA = {"global": True, "testapp": True, "testmodel": True}


@pytest.fixture
def instance():
    return TestModel.objects.create()


@pytest.fixture
def related():
    return [TestModelRelated2.objects.create() for _ in range(3)]


def m2m_logs(instance):
    return instance.fieldlog_set.filter(field="test_many_to_many_field").order_by("pk")


@pytest.mark.django_db(transaction=True)
class TestM2MLogging:
    def test_add(self, instance, related):
        instance.test_many_to_many_field.add(*related)

        log = m2m_logs(instance).get()
        assert log.old_value == []
        assert log.new_value == sorted(obj.pk for obj in related)
        assert not log.created
        assert log.extra_data == CALLBACKS_EXTRA_DATA

    def test_add_existing_is_not_logged(self, instance, related):
        instance.test_many_to_many_field.add(*related)
        instance.test_many_to_many_field.add(related[0])

        assert m2m_logs(instance).count() == 1

    def test_remove(self, instance, related):
        instance.test_many_to_many_field.add(*related)
        instance.test_many_to_many_field.remove(related[0])

        log = m2m_logs(instance).last()
        assert log.old_value == sorted(obj.pk for obj in related)
        assert log.new_value == sorted(obj.pk for obj in related[1:])
        assert log.previous_log == m2m_logs(instance).first()

    def test_clear(self, instance, related):
        instance.test_many_to_many_field.add(*related)
        instance.test_many_to_many_field.clear()

        log = m2m_logs(instance).last()
        assert log.old_value == sorted(obj.pk for obj in related)
        assert log.new_value == []

    def test_set(self, instance, related):
        first, second, third = related
        instance.test_many_to_many_field.add(first, second)
        instance.test_many_to_many_field.set([second, third])

        log = m2m_logs(instance).last()
        assert log.new_value == sorted([second.pk, third.pk])
        assert set(instance.test_many_to_many_field.values_list("pk", flat=True)) == {
            second.pk,
            third.pk,
        }

    def test_reverse_add(self, instance, related):
        related[0].test_reverse_m2m.add(instance)

        log = m2m_logs(instance).get()
        assert log.old_value == []
        assert log.new_value == [related[0].pk]

    def test_reverse_clear(self, instance, related):
        instance.test_many_to_many_field.add(*related)
        other_instance = TestModel.objects.create()
        other_instance.test_many_to_many_field.add(related[0])

        related[0].test_reverse_m2m.clear()

        log = m2m_logs(instance).last()
        assert log.old_value == sorted(obj.pk for obj in related)
        assert log.new_value == sorted(obj.pk for obj in related[1:])

        other_log = m2m_logs(other_instance).last()
        assert other_log.old_value == [related[0].pk]
        assert other_log.new_value == []


@pytest.mark.django_db(transaction=True)
def test_log_m2m_fields_on_unconfigured_model(instance, related):
    field = TestModel._meta.get_field("test_many_to_many_field")
    assert fieldlogger.log_m2m_fields(TestModelRelated, field, {}) == {}


@pytest.mark.django_db(transaction=True)
def test_log_m2m_fields_without_changes(instance, related):
    instance.test_many_to_many_field.add(*related)
    field = TestModel._meta.get_field("test_many_to_many_field")

    old_state = fieldlogger.m2m_pks(field, [instance.pk])
    assert fieldlogger.log_m2m_fields(TestModel, field, old_state) == {}
    assert m2m_logs(instance).count() == 1


@pytest.mark.django_db(transaction=True)
def test_receiver_ignores_unknown_through_models():
    signals.m2m_changed_log_fields(
        object, instance=None, action="pre_add", reverse=False, model=None, pk_set=None
    )


@pytest.mark.django_db(transaction=True)
def test_receiver_ignores_post_without_pre_state(instance):
    through = TestModel.test_many_to_many_field.through
    signals.m2m_changed_log_fields(
        through,
        instance=instance,
        action="post_add",
        reverse=False,
        model=TestModelRelated2,
        pk_set=set(),
    )

    assert m2m_logs(instance).count() == 0


@pytest.mark.django_db(transaction=True)
def test_m2m_without_pk_returning_support(monkeypatch, instance, related):
    monkeypatch.setattr(
        fieldlogger, "db_supports_returning_pks", lambda *args, **kwargs: False
    )

    instance.test_many_to_many_field.add(related[0])

    log = m2m_logs(instance).get()
    assert log.pk and log.new_value == [related[0].pk]
