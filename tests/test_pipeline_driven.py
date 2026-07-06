"""End-to-end: qa_pipeline_start -> qa_pipeline_step (skip + inject) -> qa_pipeline_report
over the actual MCP tool functions, against the local demo fixture server."""

from __future__ import annotations

import json

import pytest

pytestmark = pytest.mark.asyncio


async def test_driven_pipeline_skip_then_inject_then_report(demo_server: str) -> None:
    from qai import mcp_server

    start_raw = await mcp_server.qa_pipeline_start(demo_server, own_target=True)
    start = json.loads(start_raw)
    assert "error" not in start
    session_id = start["session_id"]
    assert start["cursor"] == 0
    assert [s["name"] for s in start["steps"]] == ["recon", "security_headers"]
    assert all(s["status"] == "pending" for s in start["steps"])

    try:
        # Step 1: run recon for real (not skippable, but we run it normally).
        after_recon_raw = await mcp_server.qa_pipeline_step(session_id)
        after_recon = json.loads(after_recon_raw)
        assert after_recon["cursor"] == 1
        assert after_recon["steps"][0]["status"] == "done"
        assert after_recon["steps"][1]["status"] == "pending"

        # Step 2: skip the security_headers stage — no plugin_findings should appear.
        after_skip_raw = await mcp_server.qa_pipeline_step(session_id, skip=True)
        after_skip = json.loads(after_skip_raw)
        assert after_skip["cursor"] == 2
        assert after_skip["steps"][1]["status"] == "skipped"
        assert after_skip["last_step_output"] == []

        report_raw = await mcp_server.qa_pipeline_report(session_id)
        report = json.loads(report_raw)
        assert report["plugin_findings"] == [], "skipped stage must have no side effect"
    finally:
        await mcp_server.qa_pipeline_abort(session_id)


async def test_driven_pipeline_inject_reaches_non_skipped_stage(demo_server: str) -> None:
    from qai import mcp_server

    start = json.loads(await mcp_server.qa_pipeline_start(demo_server, own_target=True))
    session_id = start["session_id"]

    try:
        await mcp_server.qa_pipeline_step(session_id)  # recon
        step_raw = await mcp_server.qa_pipeline_step(
            session_id, inject={"notes": "focus on auth headers"}
        )
        step = json.loads(step_raw)
        assert step["steps"][1]["status"] == "done"
        # demo_target sends no security headers -> the non-skipped check stage found some.
        assert step["last_step_output"], "security_headers should have found missing headers"

        report = json.loads(await mcp_server.qa_pipeline_report(session_id))
        assert report["plugin_findings"]
    finally:
        await mcp_server.qa_pipeline_abort(session_id)


async def test_pipeline_step_with_mismatched_config_stage_errors(demo_server: str) -> None:
    from qai import mcp_server

    start = json.loads(await mcp_server.qa_pipeline_start(demo_server, own_target=True))
    session_id = start["session_id"]

    try:
        # cursor is at "recon" (step 0); a security_headers config there must error.
        result = json.loads(
            await mcp_server.qa_pipeline_step(
                session_id, config={"stage": "security_headers"}
            )
        )
        assert result.get("error_type") == "InvalidStepConfigError"
    finally:
        await mcp_server.qa_pipeline_abort(session_id)


async def test_pipeline_abort_frees_session(demo_server: str) -> None:
    from qai import mcp_server

    start = json.loads(await mcp_server.qa_pipeline_start(demo_server, own_target=True))
    session_id = start["session_id"]

    ok = json.loads(await mcp_server.qa_pipeline_abort(session_id))
    assert ok == {"ok": True}

    after = json.loads(await mcp_server.qa_pipeline_step(session_id))
    assert after.get("error_type") == "UnknownSessionError"
