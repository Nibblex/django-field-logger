"""Custom JSON classes for the ENCODER/DECODER settings tests. Kept free of
model imports so that a settings module can reference them."""

from dataclasses import dataclass
from json import JSONDecoder

from fieldlogger.encoding import Encoder


@dataclass
class Point:
    x: int
    y: int


class PointEncoder(Encoder):
    """Extends the default encoder, as the README suggests."""

    def default(self, obj):
        if isinstance(obj, Point):
            return {"__point__": [obj.x, obj.y]}
        return super().default(obj)


class PointDecoder(JSONDecoder):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, object_hook=self.object_hook, **kwargs)

    @staticmethod
    def object_hook(obj):
        if set(obj) == {"__point__"}:
            return Point(*obj["__point__"])
        return obj
