"""run_scan(plugins=[...]) integration + backward-compat: plugins=None (default) must
produce a byte-for-byte-identical RunReport except the always-present, empty
plugin_findings field."""

from __future__ import annotations

from pathlib import Path

import pytest

from qai.engine.runner import run_crawl, run_scan

pytestmark = pytest.mark.asyncio

_REPO_PATH = str(Path(__file__).resolve().parents[1] / "qai" / "demo_target")


async def test_run_scan_with_security_headers_plugin_populates_plugin_findings(
    demo_server: str,
) -> None:
    report = await run_scan(
        demo_server, _REPO_PATH, headless=True, safe_mode=True, plugins=["security_headers"]
    )
    assert report.plugin_findings, "demo_target sends no security headers by default"
    assert all(f.plugin == "security_headers" for f in report.plugin_findings)


async def test_run_scan_without_plugins_is_byte_for_byte_backward_compatible(
    demo_server: str,
) -> None:
    without_plugins = await run_scan(demo_server, _REPO_PATH, headless=True, safe_mode=True)
    with_none_plugins = await run_scan(
        demo_server, _REPO_PATH, headless=True, safe_mode=True, plugins=None
    )

    dump_a = without_plugins.model_dump(mode="json", exclude={"run_id", "started_at", "finished_at"})
    dump_b = with_none_plugins.model_dump(
        mode="json", exclude={"run_id", "started_at", "finished_at"}
    )
    assert dump_a == dump_b
    assert without_plugins.plugin_findings == []


async def test_run_crawl_unaffected_by_plugin_wiring(demo_server: str) -> None:
    """Regression guard (06-review.md): run_crawl doesn't call _recon and must stay
    fully unaffected by the plugins plumbing added to run_scan."""
    report = await run_crawl(demo_server, _REPO_PATH, headless=True, safe_mode=True)
    assert report.root_url == demo_server
    assert report.plugin_findings == []
