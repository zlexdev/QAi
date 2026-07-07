"""MCP server exposing the qai engine as tools for AI agents.

This is the SaaS-boundary CUT#6 stand-in for the MVP: the same engine, the same
``Finding[]``/``RunReport`` contract, wrapped as MCP tools instead of a REST facade.
The engine never imports this module — the boundary invariant holds both ways.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from pydantic import TypeAdapter, ValidationError

from qai.engine.capture import BrowserPool, CaptureSession
from qai.engine.contracts import CookieSpec, CrawlBudget, RunReport
from qai.engine.errors import InvalidCookieSpecError, InvalidStepConfigError, QaiError
from qai.engine.logging import configure_logging
from qai.engine.pipeline.contracts import (
    AgentDirective,
    PentestContext,
    Stage,
    StepConfig,
    StepInfo,
)
from qai.engine.pipeline.pipeline import Pipeline
from qai.engine.pipeline.session import SqliteSessionStore
from qai.engine.pipeline.stages import CheckStage, ReconStage
from qai.engine.plugins import (
    checks as _plugin_checks,  # noqa: F401 — side-effect import: registers built-in checks
)
from qai.engine.plugins.registry import iter_checks
from qai.engine.reporter import Reporter
from qai.engine.runner import run_crawl, run_scan, validate_url

_STEP_CONFIG_ADAPTER: TypeAdapter[StepConfig] = TypeAdapter(StepConfig)

configure_logging()

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_DEFAULT_PIPELINE_PLUGINS = ["security_headers"]
_REAP_INTERVAL_SECONDS = 60.0

# Durable session state (ctx/steps/cursor) — survives an MCP server restart.
_SESSION_STORE = SqliteSessionStore(Path("qai-reports") / ".pipeline_sessions.sqlite3")
# Live, non-persistable objects (the actual open browser + pipeline instance), keyed by
# session_id. Lost on process restart — see 05-risks.md R-3; a step call after a
# restart lazily rebuilds this from the durable ctx/steps.
_LIVE_PIPELINES: dict[str, tuple[Pipeline, BrowserPool, CaptureSession]] = {}
# One lock per live session_id — serializes step/report/abort against each other so two
# concurrent MCP calls on the same session can't race the cursor/SQLite save. Entries are
# evicted on abort so this dict tracks only currently-live sessions, not every one ever seen.
_SESSION_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(session_id: str) -> asyncio.Lock:
    lock = _SESSION_LOCKS.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _SESSION_LOCKS[session_id] = lock
    return lock


async def _reap_idle_pools_loop() -> None:
    """Background loop (R-6 mitigation) — evicts BrowserPools idle past IDLE_TTL_SECONDS
    so an agent that never calls qa_pipeline_abort doesn't leak a live browser process
    forever. The SQLite row survives; a later qa_pipeline_step still resumes (R-3)."""
    while True:
        await asyncio.sleep(_REAP_INTERVAL_SECONDS)
        reaped = await _SESSION_STORE.reap_idle_pools()
        for session_id in reaped:
            _LIVE_PIPELINES.pop(session_id, None)


@asynccontextmanager
async def _lifespan(_server: FastMCP) -> AsyncIterator[None]:
    task = asyncio.create_task(_reap_idle_pools_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


mcp = FastMCP("qai", lifespan=_lifespan)


def _resolve_safe_mode(url: str, own_target: bool) -> bool:
    return not (own_target or urlparse(url).hostname in _LOCAL_HOSTS)


def _parse_cookies(raw: list[dict[str, str]] | None) -> list[CookieSpec] | None:
    """Each dict needs ``name``/``value``/``domain`` (optional ``path``/``secure``/
    ``http_only``/``same_site``) — a separate auth/SSO subdomain's cookie can be listed
    alongside the main target's, since each carries its own ``domain``."""
    if not raw:
        return None
    try:
        return [CookieSpec(**c) for c in raw]
    except ValidationError as exc:
        raise InvalidCookieSpecError(str(raw), str(exc)) from exc


@mcp.tool()
async def qa_scan(
    url: str,
    repo_path: str | None = None,
    headless: bool = True,
    parallel: int = 1,
    har_dir: str | None = None,
    own_target: bool = False,
    direct_mode: bool = False,
    cookies: list[dict[str, str]] | None = None,
    plugins: list[str] | None = None,
) -> str:
    """Run the full qai pipeline against ``url`` and return a JSON RunReport.

    Args:
        url: Target URL to scan.
        repo_path: Optional path to the target's source repo — enables file:line
            correlation of findings back to the FastAPI handler that produced them.
        headless: Run the browser headless (default) or headed for debugging.
        parallel: Number of concurrent tabs to fan fuzz cases across (each tagged
            ``tab_id`` in the returned findings, for log/request correlation).
        har_dir: If set, records a ``.har`` per tab under this directory.
        own_target: Must be True to actually submit fuzz payloads against a non-local
            host — without it, a non-local URL is only page-modeled (no fill/submit),
            so an agent can never accidentally fuzz a production site it doesn't own.
        direct_mode: after one baseline UI submit per form, fuzz the rest straight over
            HTTP (faster, bypasses client-side maxlength/type constraints); falls back
            to the UI path per-form when the baseline body isn't a simple shape.
        cookies: auth cookies injected before any navigation, one dict per cookie with
            keys ``name``/``value``/``domain`` (optional ``path``/``secure``/
            ``http_only``/``same_site``) — lets the scan reach pages behind a login
            wall; a separate auth/SSO subdomain's cookie can be listed alongside the
            main target's since each carries its own domain.
        plugins: names of registered check plugins to run as an extra pass (e.g.
            ``["security_headers"]``). ``None`` (default) runs none — identical
            behaviour to before this param existed, except the always-present
            ``plugin_findings: []`` field.
    """
    safe_mode = _resolve_safe_mode(url, own_target)
    try:
        report = await run_scan(
            url,
            repo_path,
            headless=headless,
            max_parallel=parallel,
            har_dir=har_dir,
            safe_mode=safe_mode,
            direct_mode=direct_mode,
            cookies=_parse_cookies(cookies),
            plugins=plugins,
        )
    except QaiError as exc:
        return json.dumps({"error": str(exc), "error_type": type(exc).__name__})
    return report.model_dump_json()


@mcp.tool()
async def qa_scan_html(
    url: str,
    repo_path: str | None = None,
    out_path: str = "qai-report.html",
    headless: bool = True,
    parallel: int = 1,
    own_target: bool = False,
) -> str:
    """Run a scan and write a self-contained dark-themed HTML report to ``out_path``.

    Use this when a human will read the result — the HTML report is the polished
    surface (clickable file:line, severity-colored rows). Returns the JSON summary
    plus the written path. See ``qa_scan`` for the ``own_target``/safe-mode rule.
    """
    safe_mode = _resolve_safe_mode(url, own_target)
    try:
        report = await run_scan(
            url, repo_path, headless=headless, max_parallel=parallel, safe_mode=safe_mode
        )
    except QaiError as exc:
        return json.dumps({"error": str(exc), "error_type": type(exc).__name__})
    path = Path(out_path)
    Reporter().write_html(report, path)
    return json.dumps(
        {
            "run_id": report.run_id,
            "ok": report.ok,
            "safe_mode": report.safe_mode,
            "findings_count": len(report.findings),
            "html_report": str(path.resolve()),
        }
    )


@mcp.tool()
async def qa_crawl(
    url: str,
    repo_path: str | None = None,
    headless: bool = True,
    max_depth: int = 2,
    max_actions: int = 50,
    wall_clock_seconds: int = 180,
    allow_destructive: list[str] | None = None,
    parallel: int = 1,
    own_target: bool = False,
    direct_mode: bool = False,
    cookies: list[dict[str, str]] | None = None,
) -> str:
    """Discover same-origin pages (BFS, budgeted) from ``url`` and fuzz every form found.

    Links/buttons whose text matches a destructive keyword (delete/pay/withdraw/transfer/
    удалить/оплатить/... — see ``qai.engine.risk``) are never clicked unless their
    selector is in ``allow_destructive``. This is a heuristic, not a security guarantee —
    review the returned ``skipped_destructive`` list yourself.

    See ``qa_scan`` for the ``own_target``/safe-mode rule and the ``cookies`` shape —
    both apply identically here, per discovered page.
    """
    safe_mode = _resolve_safe_mode(url, own_target)
    budget = CrawlBudget(
        max_depth=max_depth, max_actions=max_actions, wall_clock_seconds=wall_clock_seconds
    )
    try:
        report = await run_crawl(
            url,
            repo_path,
            headless=headless,
            budget=budget,
            allowlist=frozenset(allow_destructive or []),
            max_parallel=parallel,
            safe_mode=safe_mode,
            direct_mode=direct_mode,
            cookies=_parse_cookies(cookies),
        )
    except QaiError as exc:
        return json.dumps({"error": str(exc), "error_type": type(exc).__name__})
    return report.model_dump_json()


def _build_stages(session: CaptureSession, plugin_names: list[str]) -> list[Stage]:
    return [ReconStage(session), *(CheckStage(c) for c in iter_checks(plugin_names))]


def _plugin_names_from_steps(steps: list[StepInfo]) -> list[str]:
    """Recovers the plugin list from persisted StepInfo names — every step after
    ``recon`` is a CheckStage tagged with its check's registered name."""
    return [s.name for s in steps if s.name != "recon"]


async def _resume_pipeline(session_id: str) -> Pipeline:
    """Reconstructs a Pipeline for a session_id whose live objects were lost (process
    restart since qa_pipeline_start, or a first-ever qa_pipeline_step in a fresh
    process) — re-opens a fresh CaptureSession at ctx.target_url before returning it.
    See 05-risks.md R-3."""
    ctx, steps, cursor = await _SESSION_STORE.load(session_id)
    pool = await BrowserPool.create(headless=True)
    session = CaptureSession(pool=pool, cookies=ctx.cookies)
    await session.__aenter__()
    stages = _build_stages(session, _plugin_names_from_steps(steps))
    pipeline = Pipeline(session_id, stages, ctx)
    pipeline.restore(steps, cursor)
    _SESSION_STORE.set_pool(session_id, pool)
    _LIVE_PIPELINES[session_id] = (pipeline, pool, session)
    return pipeline


async def _get_pipeline(session_id: str) -> Pipeline:
    live = _LIVE_PIPELINES.get(session_id)
    if live is not None:
        return live[0]
    return await _resume_pipeline(session_id)


@mcp.tool()
async def qa_pipeline_start(
    url: str,
    repo_path: str | None = None,
    headless: bool = True,
    own_target: bool = False,
    cookies: list[dict[str, str]] | None = None,
    plugins: list[str] | None = None,
) -> str:
    """Start a resumable, externally-driven pentest pipeline against ``url``.

    Unlike ``qa_scan``, this opens ONE live browser session that persists across
    subsequent ``qa_pipeline_step`` calls — the caller drives it one stage at a time,
    inspecting each step's output before deciding whether to inject context, skip, or
    configure the next step.

    Args:
        own_target: reserved for a future active-check gating rule (deferred — this
            pilot ships only a passive check, so it has no effect yet).
        plugins: check stages to append after the fixed ``recon`` stage. ``None``
            defaults to ``["security_headers"]`` (the pilot's only check); pass ``[]``
            for a recon-only, single-stage pipeline.
    """
    del own_target  # reserved, see docstring
    try:
        target = validate_url(url)
        cookie_specs = _parse_cookies(cookies)
        plugin_names = _DEFAULT_PIPELINE_PLUGINS if plugins is None else plugins
        iter_checks(plugin_names)  # fail fast on a typo before opening a browser

        pool = await BrowserPool.create(headless=headless)
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
        )
        pipeline = Pipeline("", stages, ctx)
        session_id = await _SESSION_STORE.create(ctx, pipeline.steps)
        pipeline.bind_session_id(session_id)
        _SESSION_STORE.set_pool(session_id, pool)
        _LIVE_PIPELINES[session_id] = (pipeline, pool, session)
    except QaiError as exc:
        return json.dumps({"error": str(exc), "error_type": type(exc).__name__})
    return pipeline.to_state().model_dump_json()


@mcp.tool()
async def qa_pipeline_step(
    session_id: str,
    inject: dict[str, object] | None = None,
    skip: bool = False,
    config: dict[str, object] | None = None,
) -> str:
    """Run (or skip) exactly one stage of a started pipeline.

    Args:
        inject: an ``AgentDirective`` dict (``notes``/``focus_selectors``/
            ``focus_params``/``hints``) appended to the context for the current (and
            any later) non-skipped stage to read — allowed alongside ``skip``.
        skip: advance the cursor without running the current stage's side effects.
        config: a ``StepConfig`` dict whose ``stage`` field must match the CURRENT
            stage's name (e.g. ``{"stage": "security_headers", "required_headers": [...]}
            ``) — a mismatch raises ``InvalidStepConfigError``. Not yet consumed by any
            stage's ``__call__`` in this pilot (both pilot stages ignore it); validated
            eagerly so a caller gets fast feedback on a malformed payload.
    """
    try:
        async with _lock_for(session_id):
            pipeline = await _get_pipeline(session_id)
            directive = AgentDirective(**inject) if inject is not None else None
            if config is not None:
                _validate_step_config(pipeline, config)
            output = await pipeline.step(inject=directive, skip=skip)
            await _SESSION_STORE.save(session_id, pipeline.ctx, pipeline.steps, pipeline.cursor)
    except QaiError as exc:
        return json.dumps({"error": str(exc), "error_type": type(exc).__name__})
    return pipeline.to_state(last_step_output=output).model_dump_json()


def _validate_step_config(pipeline: Pipeline, config: dict[str, object]) -> None:
    validated = _STEP_CONFIG_ADAPTER.validate_python(config)
    if pipeline.cursor >= len(pipeline.steps):
        return
    current_stage = pipeline.steps[pipeline.cursor].name
    if validated.stage != current_stage:
        raise InvalidStepConfigError(expected_stage=current_stage, got_stage=validated.stage)


@mcp.tool()
async def qa_pipeline_report(session_id: str) -> str:
    """Return a RunReport-shaped JSON projected from the session's current
    PentestContext. Does not tear down the session — call ``qa_pipeline_abort``
    separately once done."""
    try:
        async with _lock_for(session_id):
            pipeline = await _get_pipeline(session_id)
            ctx = pipeline.ctx
        report = RunReport(
            run_id=session_id,
            target_url=ctx.target_url,
            repo_path=ctx.repo_path,
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            findings=ctx.core_findings,
            plugin_findings=ctx.plugin_findings,
        )
    except QaiError as exc:
        return json.dumps({"error": str(exc), "error_type": type(exc).__name__})
    return report.model_dump_json()


@mcp.tool()
async def qa_pipeline_abort(session_id: str) -> str:
    """Close the session's live BrowserPool (if any) and delete its SQLite row."""
    try:
        async with _lock_for(session_id):
            await _SESSION_STORE.load(session_id)  # raises UnknownSessionError if gone
            live = _LIVE_PIPELINES.pop(session_id, None)
            pool: BrowserPool | None
            if live is not None:
                _, pool, _session = live
            else:
                pool = _SESSION_STORE.evict_pool(session_id)
            if pool is not None:
                await pool.close()
            await _SESSION_STORE.delete(session_id)
        _SESSION_LOCKS.pop(session_id, None)
    except QaiError as exc:
        return json.dumps({"error": str(exc), "error_type": type(exc).__name__})
    return json.dumps({"ok": True})


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
