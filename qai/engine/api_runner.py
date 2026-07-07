"""run_api_scan — spec-driven API scanning (OpenAPI/GraphQL). Parses the spec into
``ApiOperation``s, converts each to a ``FormModel`` (Decision B: the EXISTING fuzzer/
analyzer/reporter run unmodified), and fires fuzz cases straight over HTTP (no DOM to
drive — API-scan always operates direct-request style).

NOTE on ``_fuzz_form``/``DirectExecutor`` reuse: those helpers substitute into a
form-urlencoded BODY learned from a baseline UI submission — a shape that doesn't
generalize to path/query-string API parameters (see `IMPLEMENTATION-NOTES.md`). This
module's ``_ApiRequestExecutor`` fires the actual HTTP request instead, but still
reuses ``DataGenerator`` (fuzz-case generation) and ``Analyzer`` (the oracle)
unmodified — matching Decision B's actual intent of not duplicating fuzz-case
generation or oracle logic.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode

from qai.engine.analyzer import Analyzer
from qai.engine.apispec.contracts import ApiOperation, ApiSpecKind, ApiSpecSource
from qai.engine.apispec.graphql import parse_graphql
from qai.engine.apispec.openapi import parse_openapi
from qai.engine.auth.contracts import LoginMacro
from qai.engine.auth.replayer import replay_login
from qai.engine.capture import BrowserPool, CaptureSession
from qai.engine.contracts import (
    CapturedRequest,
    CookieSpec,
    EffectBundle,
    FieldModel,
    Finding,
    HttpMethod,
    PageModel,
    PluginFinding,
    ResponseKind,
    RunReport,
)
from qai.engine.correlator import CodeCorrelator, build_route_table, require_repo
from qai.engine.fuzzer.generator import DataGenerator, FuzzPlan
from qai.engine.logging import get_logger
from qai.engine.plugins import (
    checks as _plugin_checks,  # noqa: F401 — side-effect import: registers built-in checks
)
from qai.engine.plugins.contracts import CheckContext
from qai.engine.plugins.registry import iter_checks
from qai.engine.plugins.runner import PluginRunner

_log = get_logger("api_runner")


class _ApiRequestExecutor:
    """Fires one fuzz case for one ApiOperation straight over HTTP — path params are
    substituted into the URL template, query params appended as a query string, body/
    arg params serialized as a JSON body (non-GET only)."""

    def __init__(self, session: CaptureSession, op: ApiOperation, base_url: str) -> None:
        self._session = session
        self._op = op
        self._base_url = base_url.rstrip("/")

    async def run(self, plan: FuzzPlan) -> EffectBundle:
        path = self._op.path
        query: dict[str, str] = {}
        body: dict[str, str] = {}
        for param in self._op.params:
            selector = f"{param.location}:{param.name}"
            value = plan.values.get(selector, "")
            if param.location == "path":
                path = path.replace("{" + param.name + "}", value)
            elif param.location == "query":
                query[param.name] = value
            else:  # body / arg
                body[param.name] = value

        url = self._base_url + path
        if query:
            url = f"{url}?{urlencode(query)}"

        body_str: str | None = None
        headers: dict[str, str] | None = None
        if self._op.method is not HttpMethod.GET and body:
            body_str = json.dumps(body)
            headers = {"content-type": "application/json"}

        response = await self._session.request.fetch(
            url, method=self._op.method.value, headers=headers, data=body_str
        )
        status = response.status
        await response.dispose()
        request = CapturedRequest(
            method=self._op.method,
            url=url,
            status=status,
            response_kind=ResponseKind.from_status(status),
            request_body=body_str,
            content_type=headers.get("content-type") if headers else None,
        )
        return EffectBundle(action_id=plan.case_id, tab_id=self._session.tab_id, requests=[request])


def _flatten_fields(operations: list[ApiOperation]) -> list[FieldModel]:
    return [field for op in operations for field in op.to_form_model().fields]


async def run_api_scan(
    spec: ApiSpecSource,
    base_url: str,
    repo_path: str | None = None,
    headless: bool = True,
    safe_mode: bool = True,
    cookies: list[CookieSpec] | None = None,
    login_macro: LoginMacro | None = None,
    plugins: list[str] | None = None,
) -> RunReport:
    """Parses ``spec``, converts each operation to a FormModel, and fuzzes it. Returns
    a RunReport identical in shape to ``run_scan``'s.

    Args:
        safe_mode: model/convert operations only, never fire a fuzz request — same
            fail-safe meaning as run_scan's safe_mode.
        login_macro: if given, calls replay_login first and merges its cookies with
            any explicit cookies= (macro's cookies first).
    """
    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(UTC)

    resolved_cookies = cookies
    if login_macro is not None:
        login_pool = await BrowserPool.create(headless=headless)
        try:
            auth = await replay_login(login_pool, login_macro)
        finally:
            await login_pool.close()
        resolved_cookies = [*auth.cookies, *(cookies or [])]

    if spec.kind is ApiSpecKind.OPENAPI:
        operations = parse_openapi(spec.raw)
    else:
        operations = parse_graphql(spec.raw)

    correlator: CodeCorrelator | None = None
    if repo_path:
        root = require_repo(Path(repo_path))
        correlator = CodeCorrelator(build_route_table(root), root)

    pool = await BrowserPool.create(headless=headless)
    generator = DataGenerator()
    findings: list[Finding] = []
    plugin_findings: list[PluginFinding] = []
    cases_executed = 0
    try:
        async with CaptureSession(
            run_id=run_id, tab_id="api-scan", pool=pool, cookies=resolved_cookies
        ) as session:
            if plugins:
                check_ctx = CheckContext(
                    page=PageModel(url=base_url),
                    effects=[],
                    cookies=resolved_cookies,
                    repo_path=repo_path,
                    safe_mode=safe_mode,
                )
                outcomes = await PluginRunner(iter_checks(plugins), session).run(check_ctx)
                plugin_findings = [f for outcome in outcomes for f in outcome.findings]

            if not safe_mode:
                for op in operations:
                    form = op.to_form_model()
                    executor = _ApiRequestExecutor(session, op, base_url)
                    analyzer = Analyzer()
                    for plan in generator.plans(form):
                        effect = await executor.run(plan)
                        cases_executed += 1
                        for finding in analyzer.analyze(
                            plan, effect, submit_method=form.method, page_origin=base_url
                        ):
                            if correlator is not None and finding.request is not None:
                                source = correlator.correlate(finding.request)
                                finding = finding.model_copy(update={"source_location": source})
                            findings.append(finding)
    finally:
        await pool.close()

    report = RunReport(
        run_id=run_id,
        target_url=base_url,
        repo_path=repo_path,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        forms_scanned=len(operations),
        cases_executed=cases_executed,
        safe_mode=safe_mode,
        fields_examined=_flatten_fields(operations),
        findings=findings,
        plugin_findings=plugin_findings,
    )
    _log.info(
        "api_scan_complete",
        run_id=run_id,
        operations=len(operations),
        cases=cases_executed,
        findings=len(findings),
    )
    return report
