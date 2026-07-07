"""CaptureSession.cookies() reads the LIVE browser context's jar, not a cached copy of
what was passed at construction."""

from __future__ import annotations

import pytest

from qai.engine.capture import BrowserPool, CaptureSession
from qai.engine.contracts import CookieSpec

pytestmark = pytest.mark.asyncio


async def test_cookies_roundtrip_after_navigation(demo_server: str) -> None:
    cookie = CookieSpec(name="session", value="abc123", domain="127.0.0.1")
    pool = await BrowserPool.create(headless=True)
    try:
        async with CaptureSession(pool=pool, cookies=[cookie]) as session:
            await session.open(demo_server)
            live_cookies = await session.cookies()
            by_name = {c.name: c for c in live_cookies}
            assert "session" in by_name
            assert by_name["session"].value == "abc123"
    finally:
        await pool.close()
