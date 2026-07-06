"""Reporter output formats — each renders from the same report, must agree."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from qai.engine.contracts import Finding, FindingKind, RunReport, Severity
from qai.engine.reporter import Reporter


def _report_with_one_finding() -> RunReport:
    now = datetime.now(UTC)
    finding = Finding(
        severity=Severity.HIGH,
        kind=FindingKind.SERVER_ERROR,
        action_id="form-0::input[name=\"q\"]::overflow::0",
        detail="POST /submit -> 500",
    )
    return RunReport(
        run_id="test-run",
        target_url="http://example.test",
        started_at=now,
        finished_at=now,
        forms_scanned=1,
        cases_executed=5,
        findings=[finding],
    )


def test_write_findings_contains_only_the_findings_array(tmp_path: Path) -> None:
    report = _report_with_one_finding()
    out = tmp_path / "out.findings.json"

    Reporter().write_findings(report, out)

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["detail"] == "POST /submit -> 500"
    assert payload[0]["severity"] == "high"
    # no page/state/timing noise — just the findings shape
    assert "forms_scanned" not in payload[0]
    assert "run_id" not in payload[0]


def test_write_findings_is_empty_list_when_no_findings(tmp_path: Path) -> None:
    report = _report_with_one_finding().model_copy(update={"findings": []})
    out = tmp_path / "out.findings.json"

    Reporter().write_findings(report, out)

    assert json.loads(out.read_text(encoding="utf-8")) == []
