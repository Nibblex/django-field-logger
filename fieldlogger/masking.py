"""The default mask for the values of sensitive fields (see ``mask_fields``)."""

from typing import Any

# What a masked value is logged as by default: the same text for every
# value, so it reveals neither part of the value nor its length.
MASK = "********"


def mask_value(value: Any) -> str:
    """The default masking function: returns ``MASK`` for any value."""
    return MASK
