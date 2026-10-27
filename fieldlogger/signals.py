"""Signal receivers that log field changes on every ``save()``, and
deletions of the models that log them."""

from typing import Any

from django.core.signals import setting_changed
from django.db.models import Model
from django.db.models.signals import (
    m2m_changed,
    post_delete,
    post_save,
    pre_delete,
    pre_save,
)

from .config import get_config, get_m2m_config, invalidate_config, through_model
from .context import logging_disabled
from .fieldlogger import (
    PRE_DELETE_ATTR,
    PRE_INSTANCE_ATTR,
    PRE_M2M_ATTR,
    log_deletions,
    log_fields,
    log_m2m_fields,
    m2m_pks,
)

# Models whose deletion receivers are connected. They are disconnected from
# a model that stops logging deletions: while a model has delete receivers,
# Django loads every object that QuerySet.delete() removes, to send them.
_deletion_models: set[type[Model]] = set()


def pre_save_log_fields(
    sender: type[Model],
    instance: Model,
    raw: bool = False,
    using: str | None = None,
    **kwargs: Any,
) -> None:
    """Stash the current database state of the instance before saving."""
    if raw or logging_disabled():
        # Fixture loading has nothing to compare against; inside
        # disable_logging() the state is not needed.
        return

    logging_config = get_config().get(sender)
    if logging_config is None or not instance.pk:
        return

    # Only the logged fields are compared, so only they are fetched, from
    # the same database the instance is being saved to.
    pre_instance = (
        sender._base_manager.using(using)
        .filter(pk=instance.pk)
        .only(*(field.name for field in logging_config["logging_fields"]))
        .first()
    )
    setattr(instance, PRE_INSTANCE_ATTR, pre_instance)


def post_save_log_fields(
    sender: type[Model],
    instance: Model,
    created: bool,
    update_fields: frozenset[str] | None,
    raw: bool = False,
    using: str | None = None,
    **kwargs: Any,
) -> None:
    """Log the changed fields and clean up the stashed pre-save state."""
    if raw or logging_disabled():
        # Fixture loading is a restore, not a change worth logging. In
        # both cases pre_save stashed nothing to clean up.
        return

    log_fields(sender, [instance], update_fields or frozenset(), using=using)

    if hasattr(instance, PRE_INSTANCE_ATTR):
        delattr(instance, PRE_INSTANCE_ATTR)


def m2m_changed_log_fields(
    sender: type[Model],
    instance: Model,
    action: str,
    reverse: bool,
    model: type[Model],
    pk_set: set[Any] | None,
    using: str | None = None,
    **kwargs: Any,
) -> None:
    """Log changes to the configured many-to-many fields.

    Connected to the through model of every configured field; handles
    changes made from both sides of the relation.
    """
    if logging_disabled():
        return

    m2m_config = get_m2m_config().get(sender)
    if m2m_config is None:
        return

    model_class, field = m2m_config

    if action.startswith("pre_"):
        affected_pks: list[Any]
        if not reverse:
            affected_pks = [instance.pk]
        elif pk_set is not None:
            affected_pks = list(pk_set)
        else:
            # clear() from the reverse side affects every instance
            # currently related to ``instance``.
            through = through_model(field)
            affected_pks = list(
                through._base_manager.using(using)
                .filter(**{field.m2m_reverse_field_name(): instance.pk})
                .values_list(field.m2m_field_name(), flat=True)
            )

        setattr(instance, PRE_M2M_ATTR, m2m_pks(field, affected_pks, using))

    elif hasattr(instance, PRE_M2M_ATTR):
        old_state: dict[Any, set[Any]] = getattr(instance, PRE_M2M_ATTR)
        delattr(instance, PRE_M2M_ATTR)
        log_m2m_fields(model_class, field, old_state, using=using)


def pre_delete_log_fields(
    sender: type[Model],
    instance: Model,
    using: str | None = None,
    origin: Any = None,
    **kwargs: Any,
) -> None:
    """Stash the stored state of the instance before it is deleted."""
    if logging_disabled():
        return

    logging_config = get_config().get(sender)
    if logging_config is None or not logging_config["log_deletions"]:
        return

    logging_fields = logging_config["logging_fields"]
    if not logging_fields:
        return

    # Objects that Django loaded to delete them (in QuerySet.delete() or a
    # cascade) hold the stored values, unless deferred; ``origin``, from
    # Django 4.1, tells them apart. The instance whose delete() was called
    # may hold others, e.g. an F() expression after its save().
    deferred = instance.get_deferred_fields()
    loaded = (
        origin is not None
        and origin is not instance
        and not any(field.attname in deferred for field in logging_fields)
    )
    row = (
        instance
        if loaded
        else sender._base_manager.using(using)
        .filter(pk=instance.pk)
        .only(*(field.name for field in logging_fields))
        .first()
    )
    setattr(instance, PRE_DELETE_ATTR, row)


def post_delete_log_fields(
    sender: type[Model],
    instance: Model,
    using: str | None = None,
    **kwargs: Any,
) -> None:
    """Log the deletion and clean up the stashed state."""
    if not hasattr(instance, PRE_DELETE_ATTR):
        # Logging is disabled, or the model does not log deletions.
        return

    log_deletions(sender, [instance], using=using)
    delattr(instance, PRE_DELETE_ATTR)


def connect_signals() -> None:
    """Connect the logging receivers to every configured model.

    Called from ``FieldloggerConfig.ready()`` once the app registry is
    loaded. Receivers of models no longer configured stay connected but
    do nothing, since every receiver re-checks the configuration, except
    the deletion receivers, which are disconnected.
    """
    for model_class in _deletion_models:
        pre_delete.disconnect(pre_delete_log_fields, model_class)
        post_delete.disconnect(post_delete_log_fields, model_class)
    _deletion_models.clear()

    for model_class, logging_config in get_config().items():
        pre_save.connect(pre_save_log_fields, model_class)
        post_save.connect(post_save_log_fields, model_class)
        if logging_config["log_deletions"]:
            pre_delete.connect(pre_delete_log_fields, model_class)
            post_delete.connect(post_delete_log_fields, model_class)
            _deletion_models.add(model_class)

    for through in get_m2m_config():
        m2m_changed.connect(m2m_changed_log_fields, through)


def setting_changed_receiver(sender: Any, setting: str, **kwargs: Any) -> None:
    """Rebuild the configuration and reconnect the signals when
    ``FIELD_LOGGER_SETTINGS`` is overridden (e.g. with
    ``override_settings`` in tests)."""
    if setting == "FIELD_LOGGER_SETTINGS":
        invalidate_config()
        connect_signals()


setting_changed.connect(setting_changed_receiver)
