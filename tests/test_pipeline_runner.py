"""Pipeline: step()/skip() + PipelineState projection, using spy stages (no browser)."""

from __future__ import annotations

import pytest

from qai.engine.pipeline.contracts import (
    AgentDirective,
    PentestContext,
    Stage,
    StepStatus,
)
from qai.engine.pipeline.pipeline import Pipeline

pytestmark = pytest.mark.asyncio


class _SpyStage(Stage):
    def __init__(self, name: str, skippable: bool = True) -> None:
        self.name = name
        self.skippable = skippable
        self.called = False

    async def __call__(self, ctx: PentestContext) -> PentestContext:
        self.called = True
        return ctx


def _ctx() -> PentestContext:
    return PentestContext(
        target_url="https://example.test",
        page=None,
        effects=[],
        core_findings=[],
        plugin_findings=[],
        directives=[],
        cookies=None,
        repo_path=None,
    )


async def test_skip_advances_cursor_without_calling_stage() -> None:
    stage_a, stage_b = _SpyStage("a"), _SpyStage("b")
    pipeline = Pipeline("sid", [stage_a, stage_b], _ctx())

    await pipeline.step(skip=True)

    assert pipeline.cursor == 1
    assert stage_a.called is False
    assert pipeline.steps[0].status is StepStatus.SKIPPED


async def test_inject_appends_directive_before_running_stage() -> None:
    stage_a = _SpyStage("a")
    pipeline = Pipeline("sid", [stage_a], _ctx())

    await pipeline.step(inject=AgentDirective(notes="focus on auth"))

    assert stage_a.called is True
    assert pipeline.ctx.directives[0].notes == "focus on auth"
    assert pipeline.steps[0].status is StepStatus.DONE


async def test_to_state_reflects_cursor_and_steps() -> None:
    stage_a, stage_b = _SpyStage("a"), _SpyStage("b")
    pipeline = Pipeline("sid", [stage_a, stage_b], _ctx())
    await pipeline.step()

    state = pipeline.to_state()
    assert state.cursor == 1
    assert state.steps[0].status is StepStatus.DONE
    assert state.steps[1].status is StepStatus.PENDING
    assert state.session_id == "sid"
    assert state.target_url == "https://example.test"
