"""Registry: @register_check + iter_checks + UnknownCheckError."""

from __future__ import annotations

import pytest

from qai.engine.contracts import PluginFinding
from qai.engine.errors import UnknownCheckError
from qai.engine.plugins.contracts import Check, CheckContext, CheckKind
from qai.engine.plugins.registry import _CHECK_REGISTRY, iter_checks, register_check


class _FakeCheck(Check):
    kind = CheckKind.PASSIVE

    async def run(self, ctx: CheckContext, replay: object | None = None) -> list[PluginFinding]:
        return []


def test_register_and_lookup() -> None:
    register_check("fake_registry_check")(_FakeCheck)
    try:
        [found] = iter_checks(["fake_registry_check"])
        assert found.name == "fake_registry_check"
        assert isinstance(found, _FakeCheck)
    finally:
        _CHECK_REGISTRY.pop("fake_registry_check", None)


def test_unknown_check_raises_with_available_names() -> None:
    register_check("fake_registry_check_2")(_FakeCheck)
    try:
        with pytest.raises(UnknownCheckError) as exc_info:
            iter_checks(["nope"])
        assert exc_info.value.name == "nope"
        assert "fake_registry_check_2" in exc_info.value.available
    finally:
        _CHECK_REGISTRY.pop("fake_registry_check_2", None)
