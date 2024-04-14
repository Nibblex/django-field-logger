from functools import reduce
from typing import Any


def rgetattr(obj: object, attr: str, default: Any = None) -> Any:
    return reduce(lambda obj, attr: getattr(obj, attr, default), [obj] + attr.split("."))


def rsetattr(obj: object, attr: str, val: Any) -> None:
    pre, _, post = attr.rpartition(".")
    obj = rgetattr(obj, pre) if pre else obj
    setattr(obj, post, val)
