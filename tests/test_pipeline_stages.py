"""ReconStage + generic CheckStage adapter."""

from __future__ import annotations

import pytest

from qai.engine.capture import BrowserPool, CaptureSession
from qai.engine.contracts import PageModel, PluginFinding
from qai.engine.pipeline.contracts import PentestContext
from qai.engine.pipeline.stages import CheckStage, ReconStage
from qai.engine.plugins.contracts import Check, CheckContext, CheckKind

pytestmark = pytest.mark.asyncio


class _SecondFakeCheck(Check):
    """Proves CheckStage works with ANY Check, not just security_headers."""

    name = "fake_check"
    kind = CheckKind.PASSIVE
    timeout_s = 5.0

    async def run(self, ctx: CheckContext, replay: object | None = None) -> list[PluginFinding]:
        return [
            PluginFinding(plugin=self.name, category="fake", severity="low", title="t", detail="d")
        ]


class _FailingCheck(Check):
    name = "failing_check"
    kind = CheckKind.PASSIVE
    timeout_s = 5.0

    async def run(self, ctx: CheckContext, replay: object | None = None) -> list[PluginFinding]:
        raise RuntimeError("boom")


def _ctx(page: PageModel | None = None) -> PentestContext:
    return PentestContext(
        target_url="https://example.test",
        page=page,
        effects=[],
        core_findings=[],
        plugin_findings=[],
        directives=[],
        cookies=None,
        repo_path=None,
    )


async def test_recon_stage_sets_page_and_appends_effect(demo_server: str) -> None:
    pool = await BrowserPool.create(headless=True)
    try:
        async with CaptureSession(pool=pool) as session:
            stage = ReconStage(session)
            ctx = await stage(_ctx())
            assert ctx.page is not None
            assert len(ctx.effects) == 1
            assert ctx.effects[0].requests, "recon should have captured the page-load response"
    finally:
        await pool.close()


async def test_check_stage_appends_findings_on_ok() -> None:
    ctx = _ctx(page=PageModel(url="https://example.test"))
    stage = CheckStage(_SecondFakeCheck(), CaptureSession())
    ctx = await stage(ctx)
    assert len(ctx.plugin_findings) == 1
    assert ctx.plugin_findings[0].plugin == "fake_check"


async def test_check_stage_swallows_error_and_leaves_findings_untouched() -> None:
    ctx = _ctx(page=PageModel(url="https://example.test"))
    stage = CheckStage(_FailingCheck(), CaptureSession())
    ctx = await stage(ctx)
    assert ctx.plugin_findings == []
