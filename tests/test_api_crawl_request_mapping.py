"""The REST /crawl endpoint must map each request field onto the argument that means
the same thing. Two vocabularies were previously crossed: allowed_domains (crawl SCOPE
— which hosts may be visited) was passed as the destructive-action allowlist (which
delete/pay controls may be clicked), so widening scope silently granted permission to
click destructive controls, and the hosts never reached the budget at all."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from qai.engine.contracts import CrawlReport

_KEY = {"X-API-Key": "test-secret"}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("QAI_API_KEY", "test-secret")
    from qai.api.app import app

    return TestClient(app)


def _crawl_kwargs(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> dict[str, Any]:
    """POST /v1/crawl and return the kwargs run_crawl was actually called with."""
    seen: dict[str, Any] = {}

    async def _fake_run_crawl(url: str, *args: object, **kwargs: Any) -> CrawlReport:
        seen.update(kwargs)
        now = datetime.now(UTC)
        return CrawlReport(run_id="stub", root_url=url, started_at=now, finished_at=now)

    import qai.api.routes as routes_module

    monkeypatch.setattr(routes_module, "run_crawl", _fake_run_crawl)

    submit = client.post("/v1/crawl", json=payload, headers=_KEY)
    assert submit.status_code == 202, submit.text
    job_id = submit.json()["job_id"]

    async def _poll_until_done() -> dict[str, Any]:
        for _ in range(50):
            body = client.get(f"/v1/jobs/{job_id}", headers=_KEY).json()
            if body["status"] in ("done", "error"):
                return body
            await asyncio.sleep(0.02)
        raise AssertionError("job never finished")

    result = asyncio.run(_poll_until_done())
    assert result["status"] == "done", result
    return seen


def test_allowed_domains_widens_scope_and_never_permits_destructive_clicks(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _crawl_kwargs(
        client,
        monkeypatch,
        {
            "url": "http://localhost/",
            "allowed_domains": ["sso.example.com"],
            "include_subdomains": False,
        },
    )

    assert kwargs["budget"].allowed_domains == ["sso.example.com"]
    assert kwargs["budget"].include_subdomains is False
    # The regression: an allowed HOST must never arrive as permission to click a
    # destructive control.
    assert kwargs["allowlist"] == frozenset()


def test_allow_destructive_carries_selectors_to_the_allowlist(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    kwargs = _crawl_kwargs(
        client,
        monkeypatch,
        {"url": "http://localhost/", "allow_destructive": ["#confirm-delete"]},
    )

    assert kwargs["allowlist"] == frozenset({"#confirm-delete"})
    assert kwargs["budget"].allowed_domains == []
