"""Signal receivers that log field changes on every ``save()``."""

from django.core.signals import setting_changed
from django.db.models.signals import m2m_changed, post_save, pre_save

from .config import get_config, get_m2m_config, invalidate_config
from .fieldlogger import log_fields, log_m2m_fields, m2m_pks


def pre_save_log_fields(sender, instance, raw=False, using=None, **kwargs):
    """Stash the current database state of the instance before saving."""
    if raw:
        # Fixture loading; there is nothing to compare against.
        return

    logging_config = get_config().get(sender)
    if logging_config is None or not instance.pk:
        return

    # Only the logged fields are compared, so only they are fetched, from
    # the same database the instance is being saved to.
    instance._fieldlogger_pre_instance = (
        sender._base_manager.using(using)
        .filter(pk=instance.pk)
        .only(*(field.name for field in logging_config["logging_fields"]))
        .first()
    )


def post_save_log_fields(sender, instance, created, update_fields, raw=False, **kwargs):
    """Log the changed fields and clean up the stashed pre-save state."""
    if raw:
        # Fixture loading is a restore, not a change worth logging.
        return

    log_fields(sender, [instance], update_fields or frozenset())

    if hasattr(instance, "_fieldlogger_pre_instance"):
        del instance._fieldlogger_pre_instance


def m2m_changed_log_fields(
    sender, instance, action, reverse, model, pk_set, using=None, **kwargs
):
    """Log changes to the configured many-to-many fields.

    Connected to the through model of every configured field; handles
    changes made from both sides of the relation.
    """
    m2m_config = get_m2m_config().get(sender)
    if m2m_config is None:
        return

    model_class, field = m2m_config

    if action.startswith("pre_"):
        if not reverse:
            affected_pks = [instance.pk]
        elif pk_set is not None:
            affected_pks = list(pk_set)
        else:
            # clear() from the reverse side affects every instance
            # currently related to ``instance``.
            through = field.remote_field.through
            affected_pks = list(
                through._base_manager.using(using)
                .filter(**{field.m2m_reverse_field_name(): instance.pk})
                .values_list(field.m2m_field_name(), flat=True)
            )

        instance._fieldlogger_pre_m2m = m2m_pks(field, affected_pks, using)

    elif hasattr(instance, "_fieldlogger_pre_m2m"):
        old_state = instance._fieldlogger_pre_m2m
        del instance._fieldlogger_pre_m2m
        log_m2m_fields(model_class, field, old_state, using=using)


def connect_signals():
    """Connect the logging receivers to every configured model.

    Called from ``FieldloggerConfig.ready()`` once the app registry is
    loaded. Receivers of models no longer configured stay connected but
    do nothing, since every receiver re-checks the configuration.
    """
    for model_class in get_config():
        pre_save.connect(pre_save_log_fields, model_class)
        post_save.connect(post_save_log_fields, model_class)

    for through_model in get_m2m_config():
        m2m_changed.connect(m2m_changed_log_fields, through_model)


def setting_changed_receiver(sender, setting, **kwargs):
    """Rebuild the configuration and reconnect the signals when
    ``FIELD_LOGGER_SETTINGS`` is overridden (e.g. with
    ``override_settings`` in tests)."""
    if setting == "FIELD_LOGGER_SETTINGS":
        invalidate_config()
        connect_signals()


setting_changed.connect(setting_changed_receiver)
