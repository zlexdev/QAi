---
title: QAi — report formats
---

# Report formats

Every CLI run auto-saves a report — you don't need to pass `--json`/`--html` to get one.

## Auto-save (default, every run)

```
qai-reports/<run_id>.json
qai-reports/<run_id>.md
qai-reports/<run_id>.findings.json
```

- `--report-dir DIR` — change the directory (default `./qai-reports`).
- `--no-auto-report` — disable auto-save entirely (e.g. in a CI job that only wants
  the explicit `--json`/`--html` path it already asked for).

This is in addition to, not instead of, any explicit `--json PATH` / `--html PATH` you
pass — those still go exactly where you told them to.

## Formats

| Format | Flag | Use for |
|---|---|---|
| JSON | `--json PATH` (or auto-saved) | CI, machine parsing, feeding `report.findings` back into other tooling |
| Findings-only JSON | auto-saved only (`Reporter.write_findings`) | a quick "were there any errors at all" check — just the `findings` array, no pages/states/timing |
| Markdown | auto-saved only (`Reporter.write_markdown`) | pasting into a PR description, Slack, an issue tracker |
| HTML | `--html PATH` | a human reading the result — self-contained, clickable `file:line`, severity-colored |
| Terminal | always printed | quick glance while the scan is running |

All five are rendered from the same `RunReport`/`CrawlReport` — nothing is recomputed,
so they always agree with each other.

### Markdown shape

```markdown
# QAi scan report `<run_id>`

- **Target**: https://example.com
- **Status**: FAIL
- **Forms scanned**: 1
- **Cases executed**: 26
- **Findings**: 2

| Severity | Kind | Field | Intent | Detail | Source |
|---|---|---|---|---|---|
| high | server_error | `#name` | overflow | POST .../signup -> 500 ... | `app.py:40` |
```

### Library usage

```python
from qai.engine.reporter import Reporter
from pathlib import Path

reporter = Reporter()
reporter.write_json(report, Path("out.json"))
reporter.write_markdown(report, Path("out.md"))
reporter.write_html(report, Path("out.html"))
reporter.write_findings(report, Path("out.findings.json"))
```

`Reporter` methods accept both `RunReport` (single-page scan) and `CrawlReport`
(multi-page crawl) — the crawl report exposes `target_url`/`forms_scanned`/
`cases_executed` as computed aliases so the same renderer works for both without a
special case.
