from __future__ import annotations

from qai.engine.analyzer import Analyzer
from qai.engine.contracts import (
    CapturedRequest,
    EffectBundle,
    ExpectedOutcome,
    FieldConstraints,
    FieldKind,
    FieldModel,
    FindingKind,
    FuzzCase,
    FuzzIntent,
    HttpMethod,
    ResponseKind,
)
from qai.engine.fuzzer.generator import FuzzPlan


def _plan() -> FuzzPlan:
    field = FieldModel(
        selector="#roi",
        kind=FieldKind.NUMBER,
        group_id="g1",
        constraints=FieldConstraints(),
    )
    case = FuzzCase(
        value="' OR '1'='1", intent=FuzzIntent.MALICIOUS, expect=ExpectedOutcome.REJECT_GRACEFULLY
    )
    return FuzzPlan(
        case_id="g1::#roi::malicious::0",
        field_under_test=field,
        case=case,
        values={"#roi": case.value},
    )


def test_unrelated_head_request_is_ignored_when_submit_method_given() -> None:
    """A background nav-link prefetch (HEAD) seen during the settle window must not be
    mistaken for a result of a POST-submitting form's fuzz case — the false positive
    found live on chazer.chqcode.dev (an unrelated /login?next=/docs HEAD prefetch)."""
    noise = CapturedRequest(
        method=HttpMethod.HEAD,
        url="https://example.com/login?next=/docs",
        status=0,
        response_kind=ResponseKind.NETWORK_FAIL,
    )
    effect = EffectBundle(action_id="g1::#roi::malicious::0", requests=[noise])

    findings = Analyzer().analyze(_plan(), effect, submit_method=HttpMethod.POST)

    assert findings == []


def test_matching_method_request_still_produces_a_finding() -> None:
    real = CapturedRequest(
        method=HttpMethod.POST,
        url="https://example.com/roi",
        status=500,
        response_kind=ResponseKind.SERVER_ERROR,
    )
    effect = EffectBundle(action_id="g1::#roi::malicious::0", requests=[real])

    findings = Analyzer().analyze(_plan(), effect, submit_method=HttpMethod.POST)

    assert len(findings) == 1
    assert findings[0].kind is FindingKind.SERVER_ERROR


def test_third_party_same_method_request_is_ignored_when_page_origin_given() -> None:
    """A third-party analytics beacon (Google Analytics /g/collect) shares the page's
    own POST method but not its origin — found live: 25/27 "findings" on a real site
    were failed GA beacons, nothing the fuzzed form actually caused."""
    noise = CapturedRequest(
        method=HttpMethod.POST,
        url="https://www.google-analytics.com/g/collect?v=2",
        status=0,
        response_kind=ResponseKind.NETWORK_FAIL,
    )
    effect = EffectBundle(action_id="g1::#roi::malicious::0", requests=[noise])

    findings = Analyzer().analyze(
        _plan(), effect, submit_method=HttpMethod.POST, page_origin="https://example.com/"
    )

    assert findings == []


def test_same_origin_request_still_produces_a_finding() -> None:
    real = CapturedRequest(
        method=HttpMethod.POST,
        url="https://example.com/submit",
        status=500,
        response_kind=ResponseKind.SERVER_ERROR,
    )
    effect = EffectBundle(action_id="g1::#roi::malicious::0", requests=[real])

    findings = Analyzer().analyze(
        _plan(), effect, submit_method=HttpMethod.POST, page_origin="https://example.com/"
    )

    assert len(findings) == 1
    assert findings[0].kind is FindingKind.SERVER_ERROR


def test_no_submit_method_keeps_old_unfiltered_behavior() -> None:
    noise = CapturedRequest(
        method=HttpMethod.HEAD,
        url="https://example.com/login",
        status=0,
        response_kind=ResponseKind.NETWORK_FAIL,
    )
    effect = EffectBundle(action_id="g1::#roi::malicious::0", requests=[noise])

    findings = Analyzer().analyze(_plan(), effect, submit_method=None)

    assert len(findings) == 1
    assert findings[0].kind is FindingKind.NETWORK_FAIL
