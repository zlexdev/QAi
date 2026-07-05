from __future__ import annotations

from pathlib import Path

from qai.engine.contracts import CapturedRequest, HttpMethod, ResponseKind
from qai.engine.correlator import CodeCorrelator, build_route_table

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_route_table_finds_signup_handler() -> None:
    table = build_route_table(REPO_ROOT / "qai" / "demo_target")
    entry = table.resolve(HttpMethod.POST, "/signup")
    assert entry is not None
    assert entry.handler_symbol == "signup"
    assert entry.file.endswith("app.py")
    assert entry.line > 0


def test_correlator_resolves_captured_request_to_source() -> None:
    table = build_route_table(REPO_ROOT / "qai" / "demo_target")
    correlator = CodeCorrelator(table, REPO_ROOT / "qai" / "demo_target")
    request = CapturedRequest(
        method=HttpMethod.POST,
        url="http://127.0.0.1:8000/signup",
        status=500,
        response_kind=ResponseKind.SERVER_ERROR,
    )
    source = correlator.correlate(request)
    assert source is not None
    assert source.symbol == "signup"
    assert source.file.endswith("app.py")


def test_correlator_returns_none_for_unknown_route() -> None:
    table = build_route_table(REPO_ROOT / "qai" / "demo_target")
    correlator = CodeCorrelator(table, REPO_ROOT / "qai" / "demo_target")
    request = CapturedRequest(
        method=HttpMethod.GET,
        url="http://127.0.0.1:8000/does-not-exist",
        status=404,
        response_kind=ResponseKind.CLIENT_ERROR,
    )
    assert correlator.correlate(request) is None
