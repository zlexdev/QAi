"""run_api_scan end-to-end against demo_target's bundled openapi.json."""

from __future__ import annotations

from pathlib import Path

import pytest

from qai.engine.api_runner import run_api_scan
from qai.engine.apispec.contracts import ApiSpecKind, ApiSpecSource

pytestmark = pytest.mark.asyncio

_SPEC_PATH = Path(__file__).resolve().parents[1] / "qai" / "demo_target" / "openapi.json"


async def test_run_api_scan_e2e_against_demo_target(demo_server: str) -> None:
    spec = ApiSpecSource(kind=ApiSpecKind.OPENAPI, raw=_SPEC_PATH.read_text())
    report = await run_api_scan(spec, demo_server, safe_mode=False)

    assert report.target_url == demo_server
    assert report.forms_scanned >= 3
    assert report.cases_executed > 0
    assert isinstance(report.fields_examined, list)
    assert isinstance(report.findings, list)
    assert isinstance(report.plugin_findings, list)


async def test_run_api_scan_safe_mode_executes_no_cases(demo_server: str) -> None:
    spec = ApiSpecSource(kind=ApiSpecKind.OPENAPI, raw=_SPEC_PATH.read_text())
    report = await run_api_scan(spec, demo_server, safe_mode=True)
    assert report.cases_executed == 0
    assert report.findings == []
