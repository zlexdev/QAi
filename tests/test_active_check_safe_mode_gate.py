"""safe_mode gate: an ACTIVE check must be SKIPPED (never run()) when safe_mode is
True, for BOTH PluginRunner (background pass inside run_scan) and CheckStage (the
externally-driven pipeline). PASSIVE checks are unaffected either way."""

from __future__ import annotations

import pytest

from qai.engine.capture import CaptureSession
from qai.engine.contracts import PageModel, PluginFinding
from qai.engine.pipeline.contracts import PentestContext
from qai.engine.pipeline.stages import CheckStage
from qai.engine.plugins.contracts import Check, CheckContext, CheckKind, CheckStatus
from qai.engine.plugins.replay import ReplayClient
from qai.engine.plugins.runner import PluginRunner

pytestmark = pytest.mark.asyncio


class _FakeActiveCheck(Check):
    name = "fake_active"
    kind = CheckKind.ACTIVE
    timeout_s = 5.0

    def __init__(self) -> None:
        self.called = False
        self.received_replay: ReplayClient | None = None

    async def run(self, ctx: CheckContext, replay: ReplayClient | None = None) -> list[PluginFinding]:
        self.called = True
        self.received_replay = replay
        return [PluginFinding(plugin=self.name, category="x", severity="low", title="t", detail="d")]


class _FakePassiveCheck(Check):
    name = "fake_passive"
    kind = CheckKind.PASSIVE
    timeout_s = 5.0

    def __init__(self) -> None:
        self.called = False

    async def run(self, ctx: CheckContext, replay: ReplayClient | None = None) -> list[PluginFinding]:
        self.called = True
        return [PluginFinding(plugin=self.name, category="x", severity="low", title="t", detail="d")]


def _check_ctx(safe_mode: bool) -> CheckContext:
    return CheckContext(page=PageModel(url="https://example.test"), safe_mode=safe_mode)


def _pentest_ctx(safe_mode: bool) -> PentestContext:
    return PentestContext(
        target_url="https://example.test",
        page=PageModel(url="https://example.test"),
        effects=[],
        core_findings=[],
        plugin_findings=[],
        directives=[],
        cookies=None,
        repo_path=None,
        safe_mode=safe_mode,
    )


async def test_plugin_runner_skips_active_check_when_safe_mode_true() -> None:
    check = _FakeActiveCheck()
    outcomes = await PluginRunner([check], CaptureSession()).run(_check_ctx(safe_mode=True))
    assert check.called is False
    assert outcomes[0].status is CheckStatus.SKIPPED
    assert outcomes[0].findings == []


async def test_plugin_runner_runs_active_check_with_real_replay_when_safe_mode_false() -> None:
    check = _FakeActiveCheck()
    session = CaptureSession()
    outcomes = await PluginRunner([check], session).run(_check_ctx(safe_mode=False))
    assert check.called is True
    assert isinstance(check.received_replay, ReplayClient)
    assert outcomes[0].status is CheckStatus.OK
    assert len(outcomes[0].findings) == 1


async def test_plugin_runner_passive_check_unaffected_by_safe_mode() -> None:
    check = _FakePassiveCheck()
    for safe_mode in (True, False):
        check.called = False
        outcomes = await PluginRunner([check], CaptureSession()).run(_check_ctx(safe_mode))
        assert check.called is True
        assert outcomes[0].status is CheckStatus.OK


async def test_check_stage_skips_active_check_when_safe_mode_true() -> None:
    check = _FakeActiveCheck()
    stage = CheckStage(check, CaptureSession())
    ctx = await stage(_pentest_ctx(safe_mode=True))
    assert check.called is False
    assert ctx.plugin_findings == []


async def test_check_stage_runs_active_check_with_real_replay_when_safe_mode_false() -> None:
    check = _FakeActiveCheck()
    stage = CheckStage(check, CaptureSession())
    ctx = await stage(_pentest_ctx(safe_mode=False))
    assert check.called is True
    assert isinstance(check.received_replay, ReplayClient)
    assert len(ctx.plugin_findings) == 1


async def test_check_stage_passive_check_unaffected_by_safe_mode() -> None:
    check = _FakePassiveCheck()
    for safe_mode in (True, False):
        check.called = False
        stage = CheckStage(check, CaptureSession())
        ctx = await stage(_pentest_ctx(safe_mode))
        assert check.called is True
