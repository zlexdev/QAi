from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from qai.engine.capture import CaptureSession
from qai.engine.contracts import CrawlBudget
from qai.engine.explorer import Explorer
from qai.engine.state import normalize_url

pytestmark = pytest.mark.asyncio


def _crawl_app() -> FastAPI:
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        return (
            '<a href="/a">Page A</a> '
            '<button id="delete-btn">Delete account</button>'
        )

    @app.get("/a", response_class=HTMLResponse)
    async def page_a() -> str:
        return '<a href="/b">Page B</a>'

    @app.get("/b", response_class=HTMLResponse)
    async def page_b() -> str:
        return (
            '<form id="f"><input name="q" type="text">'
            '<button type="submit">Go</button></form>'
        )

    return app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture(scope="module")
def crawl_site() -> Iterator[str]:
    port = _free_port()
    config = uvicorn.Config(_crawl_app(), host="127.0.0.1", port=port, log_level="warning")
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


async def test_explorer_visits_all_pages_and_skips_destructive(crawl_site: str) -> None:
    budget = CrawlBudget(max_depth=3, max_actions=20, wall_clock_seconds=30)
    async with CaptureSession(headless=True, run_id="t") as session:
        explorer = Explorer(session, budget)
        result = await explorer.crawl(crawl_site)

    visited_urls = {s.normalized_url for s in result.states}
    assert normalize_url(crawl_site) in visited_urls
    assert normalize_url(f"{crawl_site}/a") in visited_urls
    assert normalize_url(f"{crawl_site}/b") in visited_urls

    assert len(result.skipped_destructive) == 1
    assert result.skipped_destructive[0].selector == "#delete-btn"

    b_page = next(m for s, m in result.visited if s.normalized_url == normalize_url(f"{crawl_site}/b"))
    assert len(b_page.forms) == 1


async def test_explorer_respects_max_actions_budget(crawl_site: str) -> None:
    budget = CrawlBudget(max_depth=3, max_actions=1, wall_clock_seconds=30)
    async with CaptureSession(headless=True, run_id="t") as session:
        explorer = Explorer(session, budget)
        result = await explorer.crawl(crawl_site)

    assert result.budget_exhausted_by == "max_actions"
    # root always visited; only 1 action budget means /b is never reached
    visited_urls = {s.normalized_url for s in result.states}
    assert normalize_url(f"{crawl_site}/b") not in visited_urls
