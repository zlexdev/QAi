"""AuthBypassCheck against demo_target's fixtures: GET /api/admin/stats is reachable
with NO auth check at all (planted bug); GET /protected 403s without the session
cookie (properly protected, must NOT be flagged)."""

from __future__ import annotations

import pytest

from qai.engine.contracts import CookieSpec
from qai.engine.runner import run_scan

pytestmark = pytest.mark.asyncio

_COOKIE = CookieSpec(name="session", value="demo-session-abc123", domain="127.0.0.1")


async def test_auth_bypass_flags_the_planted_unauthenticated_route(demo_server: str) -> None:
    report = await run_scan(
        f"{demo_server}/api/admin/stats", safe_mode=False, plugins=["auth_bypass"],
        cookies=[_COOKIE],
    )
    bypass_findings = [f for f in report.plugin_findings if f.category == "auth_bypass"]
    assert bypass_findings, "auth_bypass should flag /api/admin/stats (no auth check at all)"


async def test_auth_bypass_does_not_flag_a_properly_protected_route(demo_server: str) -> None:
    report = await run_scan(
        f"{demo_server}/protected", safe_mode=False, plugins=["auth_bypass"], cookies=[_COOKIE]
    )
    bypass_findings = [f for f in report.plugin_findings if f.category == "auth_bypass"]
    assert bypass_findings == [], "a properly-protected route (403 without cookie) must not be flagged"


async def test_auth_bypass_skipped_when_safe_mode(demo_server: str) -> None:
    report = await run_scan(
        f"{demo_server}/api/admin/stats", safe_mode=True, plugins=["auth_bypass"], cookies=[_COOKIE]
    )
    assert report.plugin_findings == []
