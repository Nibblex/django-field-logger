"""Signal receivers that log field changes on every ``save()``."""

from typing import Any, Dict, FrozenSet, List, Optional, Set, Type

from django.core.signals import setting_changed
from django.db.models import Model
from django.db.models.signals import m2m_changed, post_save, pre_save

from .config import get_config, get_m2m_config, invalidate_config, through_model
from .fieldlogger import (
    PRE_INSTANCE_ATTR,
    PRE_M2M_ATTR,
    log_fields,
    log_m2m_fields,
    m2m_pks,
)


def pre_save_log_fields(
    sender: Type[Model],
    instance: Model,
    raw: bool = False,
    using: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """Stash the current database state of the instance before saving."""
    if raw:
        # Fixture loading; there is nothing to compare against.
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
    sender: Type[Model],
    instance: Model,
    created: bool,
    update_fields: Optional[FrozenSet[str]],
    raw: bool = False,
    **kwargs: Any,
) -> None:
    """Log the changed fields and clean up the stashed pre-save state."""
    if raw:
        # Fixture loading is a restore, not a change worth logging.
        return

    log_fields(sender, [instance], update_fields or frozenset())

    if hasattr(instance, PRE_INSTANCE_ATTR):
        delattr(instance, PRE_INSTANCE_ATTR)


def m2m_changed_log_fields(
    sender: Type[Model],
    instance: Model,
    action: str,
    reverse: bool,
    model: Type[Model],
    pk_set: Optional[Set[Any]],
    using: Optional[str] = None,
    **kwargs: Any,
) -> None:
    """Log changes to the configured many-to-many fields.

    Connected to the through model of every configured field; handles
    changes made from both sides of the relation.
    """
    m2m_config = get_m2m_config().get(sender)
    if m2m_config is None:
        return

    model_class, field = m2m_config

    if action.startswith("pre_"):
        affected_pks: List[Any]
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
        old_state: Dict[Any, Set[Any]] = getattr(instance, PRE_M2M_ATTR)
        delattr(instance, PRE_M2M_ATTR)
        log_m2m_fields(model_class, field, old_state, using=using)


def connect_signals() -> None:
    """Connect the logging receivers to every configured model.

    Called from ``FieldloggerConfig.ready()`` once the app registry is
    loaded. Receivers of models no longer configured stay connected but
    do nothing, since every receiver re-checks the configuration.
    """
    for model_class in get_config():
        pre_save.connect(pre_save_log_fields, model_class)
        post_save.connect(post_save_log_fields, model_class)

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
