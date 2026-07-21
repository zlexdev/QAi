from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends

from qai.api.auth import get_settings, require_api_key
from qai.api.jobs import JobStore
from qai.api.pipeline_runtime import PipelineRuntime
from qai.api.schemas import (
    ApiScanRequest,
    CrawlRequest,
    JobAccepted,
    JobKind,
    JobStatusResponse,
    LoginRecordRequest,
    PipelineStartRequest,
    PipelineStepRequest,
    ScanRequest,
)
from qai.engine.api_runner import run_api_scan
from qai.engine.apispec.contracts import ApiSpecKind, ApiSpecSource
from qai.engine.auth.recorder import record_login
from qai.engine.capture import BrowserPool
from qai.engine.contracts import CrawlBudget, TimeoutConfig
from qai.engine.pipeline.contracts import AgentDirective, PipelineState
from qai.engine.runner import run_crawl, run_scan

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

health_router = APIRouter(tags=["health"])
scan_router = APIRouter(prefix="/v1", tags=["scan"], dependencies=[Depends(require_api_key)])
jobs_router = APIRouter(prefix="/v1/jobs", tags=["jobs"], dependencies=[Depends(require_api_key)])
pipeline_router = APIRouter(
    prefix="/v1/pipeline", tags=["pipeline"], dependencies=[Depends(require_api_key)]
)

_job_store = JobStore()
_pipeline_runtime: PipelineRuntime | None = None


def get_pipeline_runtime() -> PipelineRuntime:
    global _pipeline_runtime
    if _pipeline_runtime is None:
        _pipeline_runtime = PipelineRuntime(get_settings().session_db_path)
    return _pipeline_runtime


def _resolve_safe_mode(url: str, own_target: bool) -> bool:
    return not (own_target or urlparse(url).hostname in _LOCAL_HOSTS)


def _build_timeouts(
    nav_timeout_seconds: float | None, dom_stable_timeout_seconds: float | None
) -> TimeoutConfig | None:
    if nav_timeout_seconds is None and dom_stable_timeout_seconds is None:
        return None
    overrides: dict[str, int] = {}
    if nav_timeout_seconds is not None:
        overrides["nav_ms"] = int(nav_timeout_seconds * 1000)
    if dom_stable_timeout_seconds is not None:
        overrides["dom_stable_ms"] = int(dom_stable_timeout_seconds * 1000)
    return TimeoutConfig(**overrides)


@health_router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@scan_router.post("/scan", status_code=202)
async def submit_scan(req: ScanRequest) -> JobAccepted:
    safe_mode = _resolve_safe_mode(req.url, req.own_target)
    timeouts = _build_timeouts(req.nav_timeout_seconds, req.dom_stable_timeout_seconds)

    async def _run() -> dict[str, Any]:
        report = await run_scan(
            req.url,
            req.repo_path,
            headless=req.headless,
            max_parallel=req.parallel,
            har_dir=req.har_dir,
            safe_mode=safe_mode,
            direct_mode=req.direct_mode,
            cookies=req.cookies,
            plugins=req.plugins,
            login_macro=req.login_macro,
            screenshot=req.screenshot,
            screenshot_dir=req.screenshot_dir,
            timeouts=timeouts,
        )
        return report.model_dump(mode="json")

    job = await _job_store.submit(JobKind.SCAN, _run)
    return JobAccepted(job_id=job.job_id, status=job.status)


@scan_router.post("/crawl", status_code=202)
async def submit_crawl(req: CrawlRequest) -> JobAccepted:
    safe_mode = _resolve_safe_mode(req.url, req.own_target)
    timeouts = _build_timeouts(req.nav_timeout_seconds, req.dom_stable_timeout_seconds)
    budget = CrawlBudget(
        max_depth=req.max_depth,
        max_actions=req.max_actions,
        wall_clock_seconds=req.wall_clock_seconds,
    )
    allowlist = frozenset(req.allowed_domains) if req.allowed_domains else frozenset()

    async def _run() -> dict[str, Any]:
        report = await run_crawl(
            req.url,
            req.repo_path,
            headless=req.headless,
            budget=budget,
            allowlist=allowlist,
            max_parallel=req.parallel,
            safe_mode=safe_mode,
            direct_mode=req.direct_mode,
            cookies=req.cookies,
            login_macro=req.login_macro,
            timeouts=timeouts,
            screenshot=req.screenshot,
            screenshot_dir=req.screenshot_dir,
        )
        return report.model_dump(mode="json")

    job = await _job_store.submit(JobKind.CRAWL, _run)
    return JobAccepted(job_id=job.job_id, status=job.status)


@scan_router.post("/api-scan", status_code=202)
async def submit_api_scan(req: ApiScanRequest) -> JobAccepted:
    safe_mode = _resolve_safe_mode(req.base_url, req.own_target)
    spec_source = ApiSpecSource(kind=ApiSpecKind(req.spec_kind), raw=req.spec)

    async def _run() -> dict[str, Any]:
        report = await run_api_scan(
            spec_source,
            req.base_url,
            repo_path=req.repo_path,
            headless=req.headless,
            safe_mode=safe_mode,
            cookies=req.cookies,
            login_macro=req.login_macro,
            plugins=req.plugins,
        )
        return report.model_dump(mode="json")

    job = await _job_store.submit(JobKind.API_SCAN, _run)
    return JobAccepted(job_id=job.job_id, status=job.status)


@scan_router.post("/login-record", status_code=202)
async def submit_login_record(req: LoginRecordRequest) -> JobAccepted:
    safe_mode = _resolve_safe_mode(req.login_url, req.own_target)
    if safe_mode:
        # Mirrors qa_login_record's own_target fail-safe (qai/mcp_server.py:396) —
        # returned as an immediately-ERROR job rather than a 4xx so the client's
        # polling flow doesn't need a special case for this one route.
        async def _refuse() -> dict[str, Any]:
            raise ValueError("own_target=True required to record a login against a non-local target")

        job = await _job_store.submit(JobKind.LOGIN_RECORD, _refuse)
        return JobAccepted(job_id=job.job_id, status=job.status)

    async def _run() -> dict[str, Any]:
        pool = await BrowserPool.create(headless=req.headless)
        try:
            macro, auth_result = await record_login(
                pool,
                req.login_url,
                req.username,
                req.password,
                success_indicator=req.success_indicator,
            )
        finally:
            await pool.close()
        return {"macro": macro.model_dump(mode="json"), "auth_result": auth_result.model_dump(mode="json")}

    job = await _job_store.submit(JobKind.LOGIN_RECORD, _run)
    return JobAccepted(job_id=job.job_id, status=job.status)


@jobs_router.get("/{job_id}")
async def get_job(job_id: str) -> JobStatusResponse:
    job = _job_store.get(job_id)
    return JobStatusResponse(
        job_id=job.job_id, kind=job.kind, status=job.status, result=job.result, error=job.error
    )


@pipeline_router.post("/start")
async def pipeline_start(
    req: PipelineStartRequest, runtime: PipelineRuntime = Depends(get_pipeline_runtime)
) -> PipelineState:
    safe_mode = _resolve_safe_mode(req.url, req.own_target)
    return await runtime.start(
        req.url,
        repo_path=req.repo_path,
        safe_mode=safe_mode,
        cookies=req.cookies,
        plugins=req.plugins,
        login_macro=req.login_macro,
    )


@pipeline_router.post("/{session_id}/step")
async def pipeline_step(
    session_id: str,
    req: PipelineStepRequest,
    runtime: PipelineRuntime = Depends(get_pipeline_runtime),
) -> PipelineState:
    directive = AgentDirective(**req.inject) if req.inject is not None else None
    return await runtime.step(session_id, inject=directive, skip=req.skip)


@pipeline_router.get("/{session_id}/report")
async def pipeline_report(
    session_id: str, runtime: PipelineRuntime = Depends(get_pipeline_runtime)
) -> dict[str, Any]:
    report = await runtime.report(session_id)
    return report.model_dump(mode="json")


@pipeline_router.delete("/{session_id}")
async def pipeline_abort(
    session_id: str, runtime: PipelineRuntime = Depends(get_pipeline_runtime)
) -> dict[str, bool]:
    await runtime.abort(session_id)
    return {"ok": True}
