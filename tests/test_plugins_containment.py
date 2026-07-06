"""run_with_containment / PluginRunner isolation — a slow or raising Check must never
propagate out, and gather() is used without return_exceptions=True by construction."""

from __future__ import annotations

import asyncio
import inspect

import pytest

from qai.engine.contracts import PageModel, PluginFinding
from qai.engine.plugins.contracts import Check, CheckContext, CheckKind, CheckStatus
from qai.engine.plugins.runner import PluginRunner, run_with_containment


class _SlowCheck(Check):
    kind = CheckKind.PASSIVE
    timeout_s = 0.05

    async def run(self, ctx: CheckContext, replay: object | None = None) -> list[PluginFinding]:
        await asyncio.sleep(10)
        return []


class _RaisingCheck(Check):
    kind = CheckKind.PASSIVE
    timeout_s = 5.0

    async def run(self, ctx: CheckContext, replay: object | None = None) -> list[PluginFinding]:
        raise RuntimeError("boom")


class _OkCheck(Check):
    kind = CheckKind.PASSIVE
    timeout_s = 5.0

    async def run(self, ctx: CheckContext, replay: object | None = None) -> list[PluginFinding]:
        return [
            PluginFinding(
                plugin=self.name, category="ok", severity="low", title="t", detail="d"
            )
        ]


def _ctx() -> CheckContext:
    return CheckContext(page=PageModel(url="https://example.test"))


@pytest.mark.asyncio
async def test_timeout_never_propagates() -> None:
    result, status, error = await run_with_containment(_SlowCheck().run(_ctx()), 0.05)
    assert result is None
    assert status is CheckStatus.TIMEOUT
    assert error is not None


@pytest.mark.asyncio
async def test_exception_never_propagates() -> None:
    result, status, error = await run_with_containment(_RaisingCheck().run(_ctx()), 5.0)
    assert result is None
    assert status is CheckStatus.ERROR
    assert "boom" in (error or "")


@pytest.mark.asyncio
async def test_plugin_runner_contains_mixed_outcomes() -> None:
    _SlowCheck.name = "slow"
    _RaisingCheck.name = "raising"
    _OkCheck.name = "ok"
    outcomes = await PluginRunner([_SlowCheck(), _RaisingCheck(), _OkCheck()]).run(_ctx())
    by_plugin = {o.plugin: o for o in outcomes}
    assert by_plugin["slow"].status is CheckStatus.TIMEOUT
    assert by_plugin["raising"].status is CheckStatus.ERROR
    assert by_plugin["ok"].status is CheckStatus.OK
    assert len(by_plugin["ok"].findings) == 1


def test_gather_call_site_has_no_return_exceptions() -> None:
    """PluginRunner.run's gather() call must not pass return_exceptions=True — _one()
    itself never raises, so the flag would be dead code (asserted directly on the
    gather(...) call line, not the whole docstring-carrying source blob)."""
    source = inspect.getsource(PluginRunner.run)
    gather_line = next(line for line in source.splitlines() if "asyncio.gather(" in line)
    assert "return_exceptions" not in gather_line
