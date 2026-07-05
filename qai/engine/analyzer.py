"""Analyzer — turns an EffectBundle + the fuzz intent into Findings (the error oracle).

Rule: ``valid`` must not 5xx / console-error. ``malicious``/``overflow`` must be rejected
gracefully — a 500 or a silent 200 swallow is a bug, not just an unexpected accept.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from qai.engine.contracts import (
    ConsoleLevel,
    EffectBundle,
    ExpectedOutcome,
    Finding,
    FindingKind,
    FuzzCase,
    HttpMethod,
    ResponseKind,
    Severity,
)
from qai.engine.fuzzer.generator import FuzzPlan
from qai.engine.logging import get_logger

_log = get_logger("analyzer")
_DETAIL_VALUE_PREVIEW = 80


def _preview(value: str) -> str:
    """Truncate a fuzz value for human-readable detail text (overflow cases are 100k chars)."""
    if len(value) <= _DETAIL_VALUE_PREVIEW:
        return repr(value)
    return f"{value[:_DETAIL_VALUE_PREVIEW]!r}...(+{len(value) - _DETAIL_VALUE_PREVIEW} chars)"


class Analyzer:
    """Stateless: consumes one (plan, effect) pair, emits zero or more Findings."""

    def analyze(
        self,
        plan: FuzzPlan,
        effect: EffectBundle,
        submit_method: HttpMethod | None = None,
        page_origin: str | None = None,
    ) -> list[Finding]:
        """``submit_method`` — the form's own submission method (its ``method`` attr,
        default POST); ``page_origin`` — the scanned page's own origin. Only same-
        method, same-origin requests are treated as caused by the fuzzed submission —
        a capture window can otherwise sweep in unrelated background traffic (nav-link
        prefetch HEAD requests, third-party analytics/telemetry beacons that share the
        page's own POST method but not its origin) and misattribute noise as a finding
        (found live: 25/27 "findings" on a real site were failed Google Analytics
        beacons, not anything the fuzzed form actually caused)."""
        findings: list[Finding] = []
        findings += self._request_findings(plan, effect, submit_method, page_origin)
        findings += self._console_findings(plan, effect)
        findings += self._dom_error_findings(plan, effect)
        if findings:
            _log.info(
                "finding_detected",
                case_id=plan.case_id,
                count=len(findings),
                intent=plan.case.intent.value,
            )
        return findings

    def _request_findings(
        self,
        plan: FuzzPlan,
        effect: EffectBundle,
        submit_method: HttpMethod | None,
        page_origin: str | None,
    ) -> list[Finding]:
        out: list[Finding] = []
        candidates = effect.requests
        if submit_method is not None:
            candidates = [r for r in candidates if r.method is submit_method]
        if page_origin is not None:
            expected = urlsplit(page_origin).netloc
            candidates = [r for r in candidates if urlsplit(r.url).netloc == expected]
        for req in candidates:
            if req.response_kind is ResponseKind.SERVER_ERROR:
                out.append(
                    Finding(
                        severity=Severity.HIGH,
                        kind=FindingKind.SERVER_ERROR,
                        action_id=plan.case_id,
                        tab_id=effect.tab_id,
                        detail=(
                            f"{req.method.value} {req.url} -> {req.status} "
                            f"on intent={plan.case.intent.value} value={_preview(plan.case.value)}"
                        ),
                        field_selector=plan.field_under_test.selector,
                        intent=plan.case.intent,
                        request=req,
                    )
                )
            elif req.response_kind is ResponseKind.NETWORK_FAIL:
                out.append(
                    Finding(
                        severity=Severity.MEDIUM,
                        kind=FindingKind.NETWORK_FAIL,
                        action_id=plan.case_id,
                        tab_id=effect.tab_id,
                        detail=f"{req.method.value} {req.url} network failure",
                        field_selector=plan.field_under_test.selector,
                        intent=plan.case.intent,
                        request=req,
                    )
                )
            elif self._client_error_unexpected(plan.case, req.response_kind):
                out.append(
                    Finding(
                        severity=Severity.LOW,
                        kind=FindingKind.INVARIANT,
                        action_id=plan.case_id,
                        tab_id=effect.tab_id,
                        detail=(
                            f"valid input rejected: {req.method.value} {req.url} -> {req.status}"
                        ),
                        field_selector=plan.field_under_test.selector,
                        intent=plan.case.intent,
                        request=req,
                    )
                )
        return out

    def _client_error_unexpected(self, case: FuzzCase, kind: ResponseKind) -> bool:
        from qai.engine.contracts import FuzzIntent

        return (
            case.intent is FuzzIntent.VALID
            and case.expect is ExpectedOutcome.ACCEPT
            and kind is ResponseKind.CLIENT_ERROR
        )

    def _console_findings(self, plan: FuzzPlan, effect: EffectBundle) -> list[Finding]:
        out: list[Finding] = []
        for entry in effect.console:
            if entry.level is not ConsoleLevel.ERROR:
                continue
            out.append(
                Finding(
                    severity=Severity.MEDIUM,
                    kind=FindingKind.CONSOLE_ERROR,
                    action_id=plan.case_id,
                    tab_id=effect.tab_id,
                    detail=entry.text,
                    field_selector=plan.field_under_test.selector,
                    intent=plan.case.intent,
                    console_ref=entry,
                )
            )
        return out

    def _dom_error_findings(self, plan: FuzzPlan, effect: EffectBundle) -> list[Finding]:
        """Catches errors a backend reports via a 200 + visible banner (no 5xx, no
        console.error) — the gap a pure network/console oracle misses."""
        return [
            Finding(
                severity=Severity.MEDIUM,
                kind=FindingKind.DOM_ERROR,
                action_id=plan.case_id,
                tab_id=effect.tab_id,
                detail=text,
                field_selector=plan.field_under_test.selector,
                intent=plan.case.intent,
            )
            for text in effect.dom_errors
        ]
