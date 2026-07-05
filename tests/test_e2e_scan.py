"""Gate test: mock page with a form + mock backend returning 500 -> fuzzer catches it,
correlator points at file:line. This is the MVP readiness gate from PLAN.md.
"""

from __future__ import annotations

import pytest

from qai.engine.contracts import FindingKind, Severity
from qai.engine.runner import run_scan

pytestmark = pytest.mark.asyncio


async def test_overflow_on_signup_form_is_caught_and_correlated(demo_server: str) -> None:
    from pathlib import Path

    repo_path = str(Path(__file__).resolve().parents[1] / "qai" / "demo_target")

    report = await run_scan(demo_server, repo_path, headless=True)

    assert report.forms_scanned == 1
    assert report.cases_executed > 0

    server_errors = [f for f in report.findings if f.kind is FindingKind.SERVER_ERROR]
    assert server_errors, "expected the overflow case to trip the unguarded length check"

    hit = server_errors[0]
    assert hit.severity is Severity.HIGH
    assert hit.source_location is not None
    assert hit.source_location.file.endswith("app.py")
    assert hit.source_location.symbol == "signup"


async def test_parallel_tabs_tag_findings_with_distinct_tab_ids(demo_server: str) -> None:
    from pathlib import Path

    repo_path = str(Path(__file__).resolve().parents[1] / "qai" / "demo_target")

    report = await run_scan(demo_server, repo_path, headless=True, max_parallel=3)

    assert report.tabs_used > 1
    tab_ids = {f.tab_id for f in report.findings}
    assert tab_ids, "expected findings from at least one tab"
    assert all(t.startswith("tab-") for t in tab_ids)


async def test_direct_mode_still_catches_the_overflow_bug(demo_server: str) -> None:
    from pathlib import Path

    repo_path = str(Path(__file__).resolve().parents[1] / "qai" / "demo_target")

    report = await run_scan(demo_server, repo_path, headless=True, direct_mode=True)

    server_errors = [f for f in report.findings if f.kind is FindingKind.SERVER_ERROR]
    assert server_errors
    assert server_errors[0].source_location is not None


async def test_safe_mode_never_submits_anything(demo_server: str) -> None:
    report = await run_scan(demo_server, None, headless=True, safe_mode=True)

    assert report.safe_mode is True
    assert report.forms_scanned == 1
    assert report.cases_executed == 0
    assert report.findings == []
