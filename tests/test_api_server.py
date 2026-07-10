from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from qai.engine.contracts import RunReport


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("QAI_API_KEY", "test-secret")
    from qai.api.app import app

    return TestClient(app)


def test_healthz_needs_no_auth(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_scan_rejects_missing_api_key(client: TestClient) -> None:
    resp = client.post("/v1/scan", json={"url": "http://localhost/"})
    assert resp.status_code == 401


def test_scan_rejects_wrong_api_key(client: TestClient) -> None:
    resp = client.post(
        "/v1/scan", json={"url": "http://localhost/"}, headers={"X-API-Key": "nope"}
    )
    assert resp.status_code == 401


def test_scan_submit_and_poll_reaches_done(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_report = RunReport(
        run_id="stub",
        target_url="http://localhost/",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        forms_scanned=1,
        cases_executed=3,
    )

    async def _fake_run_scan(*args: object, **kwargs: object) -> RunReport:
        return stub_report

    import qai.api.routes as routes_module

    monkeypatch.setattr(routes_module, "run_scan", _fake_run_scan)

    submit = client.post(
        "/v1/scan",
        json={"url": "http://localhost/", "own_target": False},
        headers={"X-API-Key": "test-secret"},
    )
    assert submit.status_code == 202
    job_id = submit.json()["job_id"]

    async def _poll_until_done() -> dict:
        for _ in range(50):
            resp = client.get(f"/v1/jobs/{job_id}", headers={"X-API-Key": "test-secret"})
            body = resp.json()
            if body["status"] in ("done", "error"):
                return body
            await asyncio.sleep(0.02)
        raise AssertionError("job never finished")

    result = asyncio.run(_poll_until_done())
    assert result["status"] == "done"
    assert result["result"]["run_id"] == "stub"
    assert result["result"]["cases_executed"] == 3


def test_job_status_unknown_id_is_404(client: TestClient) -> None:
    resp = client.get("/v1/jobs/does-not-exist", headers={"X-API-Key": "test-secret"})
    assert resp.status_code == 404
