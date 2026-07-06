"""Runner — the walking-skeleton pipeline: URL -> PageModel -> fuzz -> Findings -> RunReport.

One vertical slice, no state-graph recursion (Phase 4 cut). Direct calls between
Analyzer/Correlator/Reporter consumers of one EffectBundle — ready to become bus
subscribers later without a data-flow rewrite (per PLAN §Шов).

Fuzz cases fan out across ``max_parallel`` independent worker sessions (each its own
browser context, tagged ``tab_id``) — the parallel-tabs mode from the stability update.
``safe_mode`` stops after page modeling: no field is ever filled, no request ever sent,
for use against targets the caller doesn't own or isn't authorized to fuzz.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from qai.engine.analyzer import Analyzer
from qai.engine.capture import BrowserPool, CaptureSession
from qai.engine.contracts import (
    CookieSpec,
    CrawlBudget,
    CrawlReport,
    EffectBundle,
    FieldModel,
    Finding,
    FormModel,
    FuzzIntent,
    HttpMethod,
    PageModel,
    PluginFinding,
    RequestTemplate,
    RunReport,
    SkippedPage,
    SkipReason,
)
from qai.engine.correlator import CodeCorrelator, build_route_table, require_repo
from qai.engine.direct_executor import DirectExecutor, learn_template
from qai.engine.errors import InvalidTargetError
from qai.engine.executor import FormExecutor
from qai.engine.explorer import Explorer
from qai.engine.fuzzer.generator import DataGenerator, FuzzPlan
from qai.engine.logging import get_logger
from qai.engine.modeler import PageModeler
from qai.engine.plugins import checks as _plugin_checks  # noqa: F401 — side-effect import: registers built-in checks
from qai.engine.plugins.contracts import CheckContext
from qai.engine.plugins.registry import iter_checks
from qai.engine.plugins.runner import PluginRunner

_log = get_logger("runner")
_URL_RE = re.compile(r"^https?://", re.IGNORECASE)

WorkItem = tuple[FormModel, FuzzPlan]


def validate_url(url: str) -> str:
    if not _URL_RE.match(url):
        raise InvalidTargetError(url, "must start with http:// or https://")
    return url


def _flatten_fields(page_model: PageModel) -> list[FieldModel]:
    return [f for form in page_model.forms for f in form.fields]


async def run_scan(
    url: str,
    repo_path: str | None = None,
    *,
    headless: bool = True,
    max_parallel: int = 1,
    har_dir: str | None = None,
    safe_mode: bool = False,
    direct_mode: bool = False,
    cookies: list[CookieSpec] | None = None,
    plugins: list[str] | None = None,
) -> RunReport:
    """Execute the full Phase 0-3 pipeline against ``url`` and return a RunReport.

    Args:
        max_parallel: number of concurrent worker sessions ("tabs") fuzz cases fan out
            across; each is tagged with its own ``tab_id`` for log/request correlation.
        har_dir: if set, each worker session records a ``.har`` under this directory.
        safe_mode: model the page only, never fill/submit — for targets the caller
            doesn't own or isn't authorized to fuzz.
        direct_mode: after one baseline UI submission per form, fire the remaining fuzz
            cases straight over HTTP (same session/cookies) instead of through the DOM —
            faster and immune to client-side maxlength/type constraints. Falls back to
            the UI executor per-form whenever the baseline body isn't a simple
            form-urlencoded shape traceable 1:1 to the form's own fields.
        cookies: injected into every worker's browser context before its first
            navigation — lets a scan reach pages behind a login wall. Each cookie's own
            ``domain`` decides which requests carry it, so cookies for a separate
            auth/SSO subdomain can be supplied alongside the main target's.
        plugins: names of registered check plugins to run as an extra pass against the
            recon page/response (e.g. ``["security_headers"]``). ``None`` (default)
            runs none — byte-for-byte identical output to before this param existed,
            except the always-present ``plugin_findings: []`` field.
    """
    url = validate_url(url)
    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(UTC)

    correlator: CodeCorrelator | None = None
    if repo_path:
        root = require_repo(Path(repo_path))
        correlator = CodeCorrelator(build_route_table(root), root)

    # One shared browser process for this whole call (recon + every fuzz worker) —
    # launching a fresh Chromium process per CaptureSession is the dominant cost of
    # --parallel N; a BrowserPool turns that into N cheap BrowserContexts instead.
    pool = await BrowserPool.create(headless=headless)
    stability_cache: dict[str, float] = {}
    try:
        page_model, recon_effect = await _recon(url, run_id, pool, stability_cache, cookies)
        forms_scanned = len(page_model.forms)
        plugin_findings = await _run_plugins(plugins, page_model, recon_effect, repo_path, cookies)

        if safe_mode or not page_model.forms:
            return RunReport(
                run_id=run_id,
                target_url=url,
                repo_path=repo_path,
                started_at=started_at,
                finished_at=datetime.now(UTC),
                forms_scanned=forms_scanned,
                cases_executed=0,
                safe_mode=safe_mode,
                fields_examined=_flatten_fields(page_model),
                findings=[],
                plugin_findings=plugin_findings,
            )

        findings, cases_executed, workers, har_paths = await _fuzz_page_model(
            url=url,
            page_model=page_model,
            run_id=run_id,
            pool=pool,
            stability_cache=stability_cache,
            headless=headless,
            max_parallel=max_parallel,
            har_dir=har_dir,
            direct_mode=direct_mode,
            correlator=correlator,
            cookies=cookies,
        )
    finally:
        await pool.close()

    report = RunReport(
        run_id=run_id,
        target_url=url,
        repo_path=repo_path,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        forms_scanned=forms_scanned,
        cases_executed=cases_executed,
        tabs_used=workers,
        har_paths=har_paths,
        fields_examined=_flatten_fields(page_model),
        findings=findings,
        plugin_findings=plugin_findings,
    )
    _log.info(
        "scan_complete",
        run_id=run_id,
        forms=forms_scanned,
        cases=cases_executed,
        tabs=workers,
        findings=len(findings),
    )
    return report


async def _recon(
    url: str,
    run_id: str,
    pool: BrowserPool,
    stability_cache: dict[str, float],
    cookies: list[CookieSpec] | None = None,
) -> tuple[PageModel, EffectBundle]:
    """One-off session that models the page — never fills or submits anything.

    Also captures one EffectBundle (the page-load response) so a plugin phase has real
    response headers to inspect. Headers don't vary per fuzz payload, so the root page
    load's response is sufficient for a header check — narrower than threading
    EffectBundles through the whole fuzz-worker fan-out.
    """
    modeler = PageModeler()
    async with CaptureSession(
        run_id=run_id,
        tab_id="recon",
        pool=pool,
        stability_cache=stability_cache,
        cookies=cookies,
    ) as session:
        effect = await session.capture("recon", lambda: session.open(url, capture_load=True))
        page_model = await modeler.model(session.page)
        return page_model, effect


async def _run_plugins(
    plugins: list[str] | None,
    page_model: PageModel,
    recon_effect: EffectBundle,
    repo_path: str | None,
    cookies: list[CookieSpec] | None,
) -> list[PluginFinding]:
    """Runs the named check plugins against the recon page/response. ``plugins=None``
    (the default) is a no-op — this is what makes the param backward-compatible."""
    if not plugins:
        return []
    check_ctx = CheckContext(
        page=page_model, effects=[recon_effect], cookies=cookies, repo_path=repo_path
    )
    outcomes = await PluginRunner(iter_checks(plugins)).run(check_ctx)
    return [f for outcome in outcomes for f in outcome.findings]


async def _fuzz_page_model(
    *,
    url: str,
    page_model: PageModel,
    run_id: str,
    pool: BrowserPool,
    stability_cache: dict[str, float],
    headless: bool,
    max_parallel: int,
    har_dir: str | None,
    direct_mode: bool,
    correlator: CodeCorrelator | None,
    cookies: list[CookieSpec] | None = None,
) -> tuple[list[Finding], int, int, list[str]]:
    """Fuzzes every field of an already-modeled page. Factored out of ``run_scan`` so
    ``run_crawl`` can fuzz Explorer's already-visited pages directly, instead of paying
    a second navigation+model pass per page via a nested ``run_scan`` call.

    Returns (findings, cases_executed, workers_used, har_paths).
    """
    generator = DataGenerator()
    work: list[WorkItem] = [
        (form, plan) for form in page_model.forms for plan in generator.plans(form)
    ]
    workers = max(1, min(max_parallel, len(work)))
    buckets: list[list[WorkItem]] = [[] for _ in range(workers)]
    for i, item in enumerate(work):
        buckets[i % workers].append(item)

    har_paths: list[str] = []
    templates: dict[str, RequestTemplate | None] = {}
    results = await asyncio.gather(
        *(
            _run_worker(
                url,
                bucket,
                tab_index,
                run_id,
                headless,
                har_dir,
                correlator,
                har_paths,
                direct_mode,
                templates,
                pool,
                stability_cache,
                cookies,
            )
            for tab_index, bucket in enumerate(buckets)
            if bucket
        )
    )
    findings: list[Finding] = [f for batch in results for f in batch]
    return findings, len(work), workers, har_paths


async def _run_worker(
    url: str,
    bucket: list[WorkItem],
    tab_index: int,
    run_id: str,
    headless: bool,
    har_dir: str | None,
    correlator: CodeCorrelator | None,
    har_paths: list[str],
    direct_mode: bool,
    templates: dict[str, RequestTemplate | None],
    pool: BrowserPool,
    stability_cache: dict[str, float],
    cookies: list[CookieSpec] | None = None,
) -> list[Finding]:
    tab_id = f"tab-{tab_index}"
    har_path = str(Path(har_dir) / f"{run_id}-{tab_id}.har") if har_dir else None
    if har_path:
        har_paths.append(har_path)

    findings: list[Finding] = []
    async with CaptureSession(
        headless=headless,
        run_id=run_id,
        tab_id=tab_id,
        har_path=har_path,
        pool=pool,
        stability_cache=stability_cache,
        cookies=cookies,
    ) as session:
        executor = FormExecutor(session)
        await session.open(url)
        analyzer = Analyzer()
        for form, plan in bucket:
            template = templates.get(form.group_id) if direct_mode else None
            used_ui = template is None
            if template is not None:
                effect = await DirectExecutor(session, template).run(plan)
            else:
                effect = await executor.run(form, plan)
                if direct_mode and form.group_id not in templates and plan.case.intent is FuzzIntent.VALID:
                    templates[form.group_id] = _learn_from_effect(form, effect)

            for finding in analyzer.analyze(
                plan, effect, submit_method=form.method, page_origin=url
            ):
                if correlator is not None and finding.request is not None:
                    source = correlator.correlate(finding.request)
                    finding = finding.model_copy(update={"source_location": source})
                findings.append(finding)

            if used_ui:
                # Only UI-driven cases touch the DOM — a reload keeps the next case's
                # baseline fields clean. Direct-request cases never navigate.
                await session.open(url)
    return findings


def _learn_from_effect(form: FormModel, effect: EffectBundle) -> RequestTemplate | None:
    """Try every non-GET request seen during the baseline submission — the form's own
    endpoint is usually the only one, but pick the first that yields a usable template."""
    for req in effect.requests:
        if req.method is HttpMethod.GET:
            continue
        template = learn_template(form, req)
        if template is not None:
            return template
    return None


async def run_crawl(
    url: str,
    repo_path: str | None = None,
    *,
    headless: bool = True,
    budget: CrawlBudget | None = None,
    allowlist: frozenset[str] = frozenset(),
    max_parallel: int = 1,
    har_dir: str | None = None,
    safe_mode: bool = False,
    direct_mode: bool = False,
    cookies: list[CookieSpec] | None = None,
) -> CrawlReport:
    """Phase 4: discover same-origin states reachable from ``url`` (BFS, budgeted),
    then run the Phase 0-3 fuzz pipeline against every discovered page that has a form.

    Destructive-looking links/buttons (keyword heuristic, see ``qai.engine.risk``) are
    never clicked unless their selector is in ``allowlist`` — see ``CrawlReport.
    skipped_destructive`` for what was skipped. ``safe_mode``/``direct_mode``/
    ``max_parallel``/``har_dir``/``cookies`` apply to each discovered page exactly as
    they do to a single ``run_scan`` call.
    """
    root = validate_url(url)
    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(UTC)
    active_budget = budget or CrawlBudget()

    correlator: CodeCorrelator | None = None
    if repo_path:
        repo_root = require_repo(Path(repo_path))
        correlator = CodeCorrelator(build_route_table(repo_root), repo_root)

    pool = await BrowserPool.create(headless=headless)
    stability_cache: dict[str, float] = {}
    pages: list[RunReport] = []
    try:
        async with CaptureSession(
            run_id=run_id,
            tab_id="explorer",
            pool=pool,
            stability_cache=stability_cache,
            cookies=cookies,
        ) as session:
            explorer = Explorer(session, active_budget, allowlist=allowlist)
            result = await explorer.crawl(root)
            deadline = explorer.deadline

        # Fuzz Explorer's already-modeled pages directly — no second recon pass per
        # page (a plain run_scan(state.normalized_url, ...) call would re-navigate and
        # re-model a page Explorer just visited).
        # Shares Explorer's own wall-clock deadline (bug: wall_clock_seconds used to
        # bound only the discovery/BFS phase — fuzzing the pages found could still run
        # arbitrarily long past the caller's budget).
        pages_not_fuzzed: list[SkippedPage] = []
        for state, page_model in result.visited:
            if not page_model.forms:
                continue
            if time.monotonic() >= deadline:
                pages_not_fuzzed.append(
                    SkippedPage(url=state.normalized_url, reason=SkipReason.BUDGET_WALL_CLOCK)
                )
                continue
            page_started = datetime.now(UTC)
            if safe_mode:
                findings: list[Finding] = []
                cases_executed, workers = 0, 1
                har_paths: list[str] = []
            else:
                findings, cases_executed, workers, har_paths = await _fuzz_page_model(
                    url=state.normalized_url,
                    page_model=page_model,
                    run_id=run_id,
                    pool=pool,
                    stability_cache=stability_cache,
                    headless=headless,
                    max_parallel=max_parallel,
                    har_dir=har_dir,
                    direct_mode=direct_mode,
                    correlator=correlator,
                    cookies=cookies,
                )
            pages.append(
                RunReport(
                    run_id=run_id,
                    target_url=state.normalized_url,
                    repo_path=repo_path,
                    started_at=page_started,
                    finished_at=datetime.now(UTC),
                    forms_scanned=len(page_model.forms),
                    cases_executed=cases_executed,
                    tabs_used=workers,
                    har_paths=har_paths,
                    safe_mode=safe_mode,
                    fields_examined=_flatten_fields(page_model),
                    findings=findings,
                )
            )
    finally:
        await pool.close()

    report = CrawlReport(
        run_id=run_id,
        root_url=root,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        states_visited=result.states,
        pages=pages,
        pages_not_visited=result.not_visited,
        pages_not_fuzzed=pages_not_fuzzed,
        skipped_destructive=result.skipped_destructive,
        budget_exhausted_by=result.budget_exhausted_by
        or ("wall_clock" if pages_not_fuzzed else None),
    )
    _log.info(
        "crawl_complete",
        run_id=run_id,
        states=len(result.states),
        pages_with_forms=len(pages),
        skipped_destructive=len(result.skipped_destructive),
        findings=len(report.findings),
    )
    return report
