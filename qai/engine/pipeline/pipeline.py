"""Pipeline — fixed-stage-list runner with step()/skip() + PipelineState projection."""

from __future__ import annotations

import time

from qai.engine.contracts import PluginFinding
from qai.engine.logging import get_logger
from qai.engine.pipeline.contracts import (
    AgentDirective,
    PentestContext,
    PipelineState,
    Stage,
    StepInfo,
    StepStatus,
)

_log = get_logger("pipeline")


class Pipeline:
    def __init__(self, session_id: str, stages: list[Stage], ctx: PentestContext) -> None:
        self._session_id = session_id
        self._stages = stages
        self._ctx = ctx
        self._steps = [
            StepInfo(name=s.name, skippable=s.skippable, status=StepStatus.PENDING)
            for s in stages
        ]
        self._cursor = 0

    @property
    def ctx(self) -> PentestContext:
        return self._ctx

    @property
    def steps(self) -> list[StepInfo]:
        return self._steps

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def session_id(self) -> str:
        return self._session_id

    def bind_session_id(self, session_id: str) -> None:
        """Set once the durable SessionStore has minted the real id (Pipeline itself
        doesn't own id generation — SessionStore.create() does)."""
        self._session_id = session_id

    def restore(self, steps: list[StepInfo], cursor: int) -> None:
        """Rehydrate step/cursor state loaded from SessionStore (restart-resume path)."""
        self._steps = steps
        self._cursor = cursor

    @property
    def done(self) -> bool:
        return self._cursor >= len(self._stages)

    async def step(
        self,
        *,
        inject: AgentDirective | None = None,
        skip: bool = False,
    ) -> list[PluginFinding]:
        """Runs (or skips) exactly one stage, advancing the cursor. Returns the new
        plugin findings produced by this step (empty on skip/error/timeout)."""
        if self.done:
            return []
        if inject is not None:
            self._ctx.directives.append(inject)

        idx = self._cursor
        stage = self._stages[idx]

        if skip:
            self._steps[idx] = self._steps[idx].model_copy(update={"status": StepStatus.SKIPPED})
            self._cursor += 1
            return []

        before = len(self._ctx.plugin_findings)
        start = time.monotonic()
        try:
            self._ctx = await stage(self._ctx)
            duration_ms = (time.monotonic() - start) * 1000
            self._steps[idx] = self._steps[idx].model_copy(
                update={"status": StepStatus.DONE, "duration_ms": duration_ms}
            )
        except Exception as exc:  # noqa: BLE001 — stage boundary, must not kill the session
            duration_ms = (time.monotonic() - start) * 1000
            _log.exception("stage_failed", stage=stage.name, error=str(exc))
            self._steps[idx] = self._steps[idx].model_copy(
                update={"status": StepStatus.ERROR, "duration_ms": duration_ms, "error": str(exc)}
            )
        self._cursor += 1
        return self._ctx.plugin_findings[before:]

    def to_state(self, *, last_step_output: list[PluginFinding] | None = None) -> PipelineState:
        return PipelineState(
            session_id=self._session_id,
            target_url=self._ctx.target_url,
            steps=self._steps,
            cursor=self._cursor,
            context_summary={
                "core_findings": len(self._ctx.core_findings),
                "plugin_findings": len(self._ctx.plugin_findings),
            },
            last_step_output=last_step_output or [],
        )
