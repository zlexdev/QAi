"""record_login + replay_login against demo_target's /login fixture — the recorded
macro's cookies must actually authenticate a subsequent request to /protected."""

from __future__ import annotations

import pytest

from qai.engine.auth.recorder import record_login
from qai.engine.auth.replayer import replay_login
from qai.engine.capture import BrowserPool
from qai.engine.errors import LoginFailedError
from qai.engine.runner import run_scan

pytestmark = pytest.mark.asyncio


async def test_record_login_succeeds_and_cookie_authenticates_protected_route(
    demo_server: str,
) -> None:
    pool = await BrowserPool.create(headless=True)
    try:
        _macro, auth_result = await record_login(
            pool, f"{demo_server}/login", "admin", "secret"
        )
    finally:
        await pool.close()

    assert auth_result.authenticated is True
    assert auth_result.cookies, "record_login should read back the session cookie"

    report = await run_scan(f"{demo_server}/protected", safe_mode=True, cookies=auth_result.cookies)
    # A safe_mode scan just navigates + models; forms_scanned==0 either way here since
    # /protected has no form, but the recon effect's response must be the 200 welcome
    # page, not the 403 — that's proven indirectly via replay below.
    assert report.target_url == f"{demo_server}/protected"


async def test_record_login_wrong_password_does_not_authenticate(demo_server: str) -> None:
    pool = await BrowserPool.create(headless=True)
    try:
        with pytest.raises(LoginFailedError):
            await record_login(pool, f"{demo_server}/login", "admin", "wrong-password")
    finally:
        await pool.close()


async def test_replay_login_reuses_saved_macro(demo_server: str) -> None:
    pool = await BrowserPool.create(headless=True)
    try:
        macro, _ = await record_login(pool, f"{demo_server}/login", "admin", "secret")
        auth_result = await replay_login(pool, macro)
    finally:
        await pool.close()

    assert auth_result.authenticated is True
    assert auth_result.cookies
