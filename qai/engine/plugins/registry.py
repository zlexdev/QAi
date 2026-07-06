"""Check registry — same decorator+dict+lookup shape as ``fuzzer/strategies.py``, but
stores CLASSES not instances (deliberate divergence, see plan's 05-risks.md R-8):
concurrent scans/pipeline sessions must not share one Check instance's mutable state."""

from __future__ import annotations

from collections.abc import Callable

from qai.engine.errors import UnknownCheckError
from qai.engine.plugins.contracts import Check

_CHECK_REGISTRY: dict[str, type[Check]] = {}


def register_check(name: str) -> Callable[[type[Check]], type[Check]]:
    def deco(cls: type[Check]) -> type[Check]:
        cls.name = name
        _CHECK_REGISTRY[name] = cls
        return cls

    return deco


def iter_checks(names: list[str]) -> list[Check]:
    """Raises UnknownCheckError immediately (not per-check inside a gather) so a typo in
    the ``plugins=[...]`` list fails fast, before any browser work starts."""
    missing = [n for n in names if n not in _CHECK_REGISTRY]
    if missing:
        raise UnknownCheckError(missing[0], available=sorted(_CHECK_REGISTRY))
    return [_CHECK_REGISTRY[n]() for n in names]
