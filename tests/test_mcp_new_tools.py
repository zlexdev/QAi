"""qa_api_scan + qa_login_record MCP tools, and backward-compat: qa_scan/qa_scan_html/
qa_crawl/qa_pipeline_start with no login_macro must produce output identical to before
this plan (same pattern as test_run_scan_plugins.py's byte-for-byte diff)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.asyncio

_SPEC_PATH = Path(__file__).resolve().parents[1] / "qai" / "demo_target" / "openapi.json"


async def test_qa_api_scan_returns_run_report_shape(demo_server: str) -> None:
    from qai import mcp_server

    raw = await mcp_server.qa_api_scan(
        _SPEC_PATH.read_text(), demo_server, own_target=True
    )
    report = json.loads(raw)
    assert "error" not in report
    assert report["target_url"] == demo_server
    assert "findings" in report
    assert "plugin_findings" in report


async def test_qa_login_record_returns_macro_and_auth_result(demo_server: str) -> None:
    from qai import mcp_server

    raw = await mcp_server.qa_login_record(
        f"{demo_server}/login", "admin", "secret", own_target=True
    )
    result = json.loads(raw)
    assert "error" not in result
    assert result["auth_result"]["authenticated"] is True
    assert result["macro"]["login_url"] == f"{demo_server}/login"


async def test_qa_login_record_requires_own_target_for_non_local() -> None:
    from qai import mcp_server

    raw = await mcp_server.qa_login_record(
        "https://example.com/login", "a", "b", own_target=False
    )
    result = json.loads(raw)
    assert result["error_type"] == "InvalidTargetError"


def _strip_nondeterministic(node: object) -> object:
    """Recursively drops run_id/timestamp keys anywhere in the tree — demo_target's
    /signup route accumulates mutable state across calls (a growing signup count
    embedded in later responses), so a byte-for-byte diff across two LIVE fuzzing
    runs must ignore wall-clock/id fields, not just the report's own top-level ones
    (unlike the safe_mode=True-only comparison in test_run_scan_plugins.py, this
    comparison actually fuzzes since demo_server is always local -> safe_mode=False)."""
    if isinstance(node, dict):
        return {
            k: _strip_nondeterministic(v)
            for k, v in node.items()
            if k not in {"run_id", "started_at", "finished_at", "date"}
        }
    if isinstance(node, list):
        return [_strip_nondeterministic(v) for v in node]
    return node


async def test_qa_scan_without_login_macro_is_backward_compatible(demo_server: str) -> None:
    from qai import mcp_server

    without = _strip_nondeterministic(json.loads(await mcp_server.qa_scan(demo_server, own_target=True)))
    with_none = _strip_nondeterministic(
        json.loads(await mcp_server.qa_scan(demo_server, own_target=True, login_macro=None))
    )
    assert without == with_none


async def test_qa_crawl_without_login_macro_is_backward_compatible(demo_server: str) -> None:
    from qai import mcp_server

    without = _strip_nondeterministic(json.loads(await mcp_server.qa_crawl(demo_server, own_target=True)))
    with_none = _strip_nondeterministic(
        json.loads(await mcp_server.qa_crawl(demo_server, own_target=True, login_macro=None))
    )
    assert without == with_none


async def test_qa_pipeline_start_own_target_gates_active_checks(demo_server: str) -> None:
    from qai import mcp_server

    start = json.loads(
        await mcp_server.qa_pipeline_start(demo_server, own_target=False, plugins=["idor"])
    )
    session_id = start["session_id"]
    try:
        await mcp_server.qa_pipeline_step(session_id)  # recon
        step = json.loads(await mcp_server.qa_pipeline_step(session_id))  # idor stage
        assert step["steps"][1]["status"] == "done"
        assert step["last_step_output"] == [], "ACTIVE check must be SKIPPED when own_target=False"
    finally:
        await mcp_server.qa_pipeline_abort(session_id)
