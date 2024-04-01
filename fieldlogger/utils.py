from functools import reduce


def rgetattr(obj, attr, *args):
    return reduce(lambda obj, attr: getattr(obj, attr, *args), [obj] + attr.split("."))


def rsetattr(obj, attr, val):
    pre, _, post = attr.rpartition(".")
    obj = rgetattr(obj, pre) if pre else obj
    setattr(obj, post, val)
