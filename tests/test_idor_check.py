"""IdorCheck against demo_target's deliberate fixture: GET /api/items/{id} returns any
id's item to any session (planted IDOR bug, see qai/demo_target/app.py)."""

from __future__ import annotations

import pytest

from qai.engine.runner import run_scan

pytestmark = pytest.mark.asyncio


async def test_idor_check_flags_the_planted_bug_when_own_target(demo_server: str) -> None:
    report = await run_scan(f"{demo_server}/api/items/1", plugins=["idor"], safe_mode=False)
    idor_findings = [f for f in report.plugin_findings if f.category == "idor_candidate"]
    assert idor_findings, "IdorCheck should flag /api/items/{id} as a candidate"
    assert all(f.plugin == "idor" for f in idor_findings)


async def test_idor_check_skipped_when_safe_mode(demo_server: str) -> None:
    report = await run_scan(f"{demo_server}/api/items/1", plugins=["idor"], safe_mode=True)
    assert report.plugin_findings == []
