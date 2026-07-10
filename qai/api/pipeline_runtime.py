from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

from qai.engine.auth.contracts import LoginMacro
from qai.engine.auth.replayer import replay_login
from qai.engine.capture import BrowserPool, CaptureSession
from qai.engine.contracts import CookieSpec, RunReport
from qai.engine.pipeline.contracts import AgentDirective, PentestContext, PipelineState, Stage, StepInfo
from qai.engine.pipeline.pipeline import Pipeline
from qai.engine.pipeline.session import SqliteSessionStore
from qai.engine.pipeline.stages import CheckStage, ReconStage
from qai.engine.plugins.registry import iter_checks
from qai.engine.runner import validate_url

DEFAULT_PIPELINE_PLUGINS = ["security_headers"]


def _build_stages(session: CaptureSession, plugin_names: list[str]) -> list[Stage]:
    return [ReconStage(session), *(CheckStage(c, session) for c in iter_checks(plugin_names))]


def _plugin_names_from_steps(steps: list[StepInfo]) -> list[str]:
    return [s.name for s in steps if s.name != "recon"]


class PipelineRuntime:
    """HTTP-facing mirror of the qa_pipeline_* MCP tools' session orchestration
    (qai/mcp_server.py:448-606) — same SqliteSessionStore path, same resume-on-restart
    behavior, so a session started via one surface can be driven from the other.
    Kept as its own small module (not shared code with mcp_server.py) to avoid
    touching the existing MCP tool implementation in this pass; see 00-overview.md
    decisions for the tradeoff."""

    def __init__(self, db_path: Path, *, headless: bool = True) -> None:
        self._store = SqliteSessionStore(db_path)
        self._live: dict[str, tuple[Pipeline, BrowserPool, CaptureSession]] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._headless = headless

    def _lock_for(self, session_id: str) -> asyncio.Lock:
        lock = self._locks.get(session_id)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[session_id] = lock
        return lock

    async def start(
        self,
        url: str,
        *,
        repo_path: str | None,
        safe_mode: bool,
        cookies: list[CookieSpec] | None,
        plugins: list[str] | None,
        login_macro: LoginMacro | None,
    ) -> PipelineState:
        target = validate_url(url)
        cookie_specs = cookies
        if login_macro is not None:
            login_pool = await BrowserPool.create(headless=self._headless)
            try:
                auth = await replay_login(login_pool, login_macro)
            finally:
                await login_pool.close()
            cookie_specs = [*auth.cookies, *(cookie_specs or [])]
        plugin_names = DEFAULT_PIPELINE_PLUGINS if plugins is None else plugins
        iter_checks(plugin_names)  # fail fast on a typo before opening a browser

        pool = await BrowserPool.create(headless=self._headless)
        session = CaptureSession(pool=pool, cookies=cookie_specs)
        await session.__aenter__()
        stages = _build_stages(session, plugin_names)
        ctx = PentestContext(
            target_url=target,
            page=None,
            effects=[],
            core_findings=[],
            plugin_findings=[],
            directives=[],
            cookies=cookie_specs,
            repo_path=repo_path,
            safe_mode=safe_mode,
        )
        pipeline = Pipeline("", stages, ctx)
        session_id = await self._store.create(ctx, pipeline.steps)
        pipeline.bind_session_id(session_id)
        self._store.set_pool(session_id, pool)
        self._live[session_id] = (pipeline, pool, session)
        return pipeline.to_state()

    async def _resume(self, session_id: str) -> Pipeline:
        ctx, steps, cursor = await self._store.load(session_id)
        pool = self._store.evict_pool(session_id) or await BrowserPool.create(headless=self._headless)
        session = CaptureSession(pool=pool, cookies=ctx.cookies)
        await session.__aenter__()
        stages = _build_stages(session, _plugin_names_from_steps(steps))
        pipeline = Pipeline(session_id, stages, ctx)
        pipeline.restore(steps, cursor)
        self._store.set_pool(session_id, pool)
        self._live[session_id] = (pipeline, pool, session)
        return pipeline

    async def _get(self, session_id: str) -> Pipeline:
        live = self._live.get(session_id)
        if live is not None:
            return live[0]
        return await self._resume(session_id)

    async def step(
        self, session_id: str, *, inject: AgentDirective | None, skip: bool
    ) -> PipelineState:
        async with self._lock_for(session_id):
            pipeline = await self._get(session_id)
            output = await pipeline.step(inject=inject, skip=skip)
            await self._store.save(session_id, pipeline.ctx, pipeline.steps, pipeline.cursor)
            return pipeline.to_state(last_step_output=output)

    async def report(self, session_id: str) -> RunReport:
        async with self._lock_for(session_id):
            pipeline = await self._get(session_id)
            ctx = pipeline.ctx
        return RunReport(
            run_id=session_id,
            target_url=ctx.target_url,
            repo_path=ctx.repo_path,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            findings=ctx.core_findings,
            plugin_findings=ctx.plugin_findings,
        )

    async def abort(self, session_id: str) -> None:
        async with self._lock_for(session_id):
            await self._store.load(session_id)  # raises UnknownSessionError if gone
            live = self._live.pop(session_id, None)
            pool = live[1] if live is not None else self._store.evict_pool(session_id)
            if pool is not None:
                await pool.close()
            await self._store.delete(session_id)
        self._locks.pop(session_id, None)
