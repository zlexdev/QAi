"""Regression guard: run_crawl must not re-navigate/re-model a page Explorer already
visited. Before this fix, run_crawl called run_scan(state.normalized_url, ...) per
page, which paid a full independent recon (navigate + model) on top of Explorer's own
visit — a silent doubling of the slowest part of the pipeline (navigation+stability
wait) for every crawled page with a form.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from qai.engine.contracts import CrawlBudget
from qai.engine.runner import run_crawl

pytestmark = pytest.mark.asyncio

_hits: dict[str, int] = {"b": 0}


def _make_app() -> FastAPI:
    app = FastAPI()

    @app.get("/", response_class=HTMLResponse)
    async def root() -> str:
        return '<a href="/b">Page B</a>'

    @app.get("/b", response_class=HTMLResponse)
    async def page_b() -> str:
        _hits["b"] += 1
        # Explicit method+action so submitting the form never re-hits GET /b itself —
        # otherwise the submission navigation would double-count against the reload
        # count this test is actually trying to isolate.
        return (
            '<form id="f" method="post" action="/submit">'
            '<input name="q" type="text"><button type="submit">Go</button></form>'
        )

    @app.post("/submit")
    async def submit() -> dict[str, bool]:
        return {"ok": True}

    return app


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture
def counting_site() -> Iterator[str]:
    _hits["b"] = 0
    port = _free_port()
    config = uvicorn.Config(_make_app(), host="127.0.0.1", port=port, log_level="warning")
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


async def test_crawl_does_not_double_navigate_a_visited_page(counting_site: str) -> None:
    budget = CrawlBudget(max_depth=2, max_actions=10, wall_clock_seconds=60)
    report = await run_crawl(counting_site, repo_path=None, budget=budget)

    assert len(report.pages) == 1
    page = report.pages[0]
    assert page.forms_scanned == 1

    # Explorer's own visit (1 GET) + the fuzz worker's initial open (1 GET) + one
    # reload after every case (cases_executed GETs) = cases_executed + 2. A regression
    # (re-adding the redundant recon that used to live in run_scan) would show up as
    # cases_executed + 3 or more.
    assert _hits["b"] == page.cases_executed + 2
