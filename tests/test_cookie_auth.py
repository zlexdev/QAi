"""Cookie-based auth: a scan must be able to reach pages behind a login wall by
injecting a cookie into the browser context before any navigation."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from qai.engine.contracts import CookieSpec
from qai.engine.runner import run_scan

pytestmark = pytest.mark.asyncio

_FORM_HTML = '<form><input name="q" type="text"><button type="submit">Go</button></form>'


def _gated_app() -> FastAPI:
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def root(request: Request) -> str:
        if request.cookies.get("session") == "ok":
            return _FORM_HTML
        return "<p>Login required</p>"

    return app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
def gated_site() -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config(_gated_app(), host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


async def test_scan_without_cookie_sees_login_wall_not_form(gated_site: str) -> None:
    report = await run_scan(gated_site, headless=True, safe_mode=True)
    assert report.forms_scanned == 0


async def test_scan_with_matching_cookie_reaches_the_form(gated_site: str) -> None:
    cookie = CookieSpec(name="session", value="ok", domain="127.0.0.1")
    report = await run_scan(gated_site, headless=True, safe_mode=True, cookies=[cookie])
    assert report.forms_scanned == 1
