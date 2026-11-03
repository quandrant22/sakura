"""Общая заглушка: каждый метод Platform бросает NotImplementedError."""
from .base import Platform


def make_stub(name: str) -> type[Platform]:
    def _not_impl(method):
        def f(self, *a, **kw):
            raise NotImplementedError(f"{name}: {method} ещё не реализован")
        f.__name__ = method
        return f

    attrs = {m: _not_impl(m) for m in Platform.__abstractmethods__}
    attrs["name"] = name
    return type(f"{name.capitalize()}Platform", (Platform,), attrs)
