from functools import reduce


def rgetattr(obj, attr, *args):
    f = lambda obj, attr: getattr(obj, attr, *args)
    return reduce(f, [obj] + attr.split("."))


def rsetattr(obj, attr, val):
    pre, _, post = attr.rpartition(".")
    obj = rgetattr(obj, pre) if pre else obj
    setattr(obj, post, val)
