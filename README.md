# QAi

Autonomous web-form fuzzer. Give it a `URL` + a repo, it finds a bug in a form
(5xx / console-error under fuzzing) and points at the exact `file:line` in your
backend where it lives — no manual test writing, no AI/paid APIs.

Full usage guide: **[docs/USAGE.md](docs/USAGE.md)**. Architecture background:
[PLAN.md](PLAN.md) / [mini-plat.md](mini-plat.md).

```
URL → page model (fields+types) → fuzz matrix per form → capture effects
(network+console+navigation) → oracle (5xx/console-error) → correlate to file:line → report
```

MVP scope: one form, one target framework (FastAPI). No state-graph crawling yet —
see [PLAN.md](PLAN.md) for the phase breakdown and [mini-plat.md](mini-plat.md) for the
full architecture this project instantiates.

## Install

```bash
uv sync --extra dev --extra demo
uv run playwright install chromium
```

## Try it against the bundled demo target

The demo target is a tiny FastAPI app with one signup form; its `name` field has an
unguarded server-side length check that a fuzzer's overflow payload reliably trips.

```bash
uv run uvicorn qai.demo_target.app:app --port 8000 &
uv run qai http://127.0.0.1:8000 --repo qai/demo_target --html report.html
```

Open `report.html` — a self-contained dark-themed report with a clickable
`qai/demo_target/app.py:LINE` next to the finding.

## Stability, parallel tabs, direct-request fuzzing, HAR

```bash
uv run qai http://127.0.0.1:8000 --repo qai/demo_target \
  --parallel 5 --direct --har ./har --i-own-this-target
```

- **Cloudflare-aware navigation** — waits out an automatic JS challenge (never solves
  or bypasses an interactive CAPTCHA; if one appears, it logs a warning and proceeds
  honestly rather than faking success) plus a best-effort `networkidle` settle.
- **`--parallel N`** — fans fuzz cases across N concurrent worker sessions ("tabs"),
  each tagged `tab-<i>`. Every `Finding`/`EffectBundle` carries its `tab_id`, so console
  logs and requests from the same tab can be stitched back into one stack later.
- **`--direct`** — after one baseline (valid) UI submission per form, remaining fuzz
  cases fire straight over HTTP via the same session's cookies (`context.request`),
  skipping the DOM entirely. Faster, and immune to client-side `maxlength`/
  `type="number"` fighting the payload. Falls back to the UI path per-form whenever the
  baseline body isn't a simple, unambiguous `application/x-www-form-urlencoded` shape.
- **`--har DIR`** — records one `.har` per tab for offline network inspection.
- **DOM error oracle** — catches errors a backend reports via `200 OK` + a visible
  banner (`[role="alert"]`, `.error`, `[aria-invalid="true"]`) with no 5xx and no
  `console.error`, which a pure network/console oracle would miss.
- **`--i-own-this-target`** — required to actually submit anything against a non-local
  host. Without it, a non-local URL is only page-modeled (fields inventoried, nothing
  filled or sent) — an accidental `qai https://example.com` never fuzzes a site you
  don't control. Localhost/127.0.0.1 targets are exempt (the normal dev loop above).

## Use as a library

```python
from qai.engine.runner import run_scan

report = await run_scan("http://127.0.0.1:8000", repo_path="qai/demo_target")
for finding in report.findings:
    print(finding.severity, finding.detail, finding.source_location)
```

## Use as an MCP server (for AI agents)

```bash
uv sync --extra mcp
uv run qai-mcp
```

Exposes two tools to any MCP-speaking agent:

- `qa_scan(url, repo_path=None, headless=True, parallel=1, har_dir=None, own_target=False, direct_mode=False)` — runs the pipeline, returns a JSON `RunReport`.
- `qa_scan_html(url, repo_path=None, out_path="qai-report.html", headless=True, parallel=1, own_target=False)` — same, plus a human-readable HTML report on disk.

`own_target` gates real submissions the same way `--i-own-this-target` does on the
CLI — an agent can safely point `qa_scan` at any URL and get a read-only page model
back unless it explicitly confirms ownership of a non-local target.

Point an agent's MCP config at `qai-mcp` (stdio transport) and it can scan any
staging target and read back structured findings — no browser access needed on
the agent's side.

## How it works

| Layer | What it does | Built on |
|---|---|---|
| `engine/capture.py` | Playwright + CDP: network, console, navigation → `EffectBundle` | Playwright |
| `engine/modeler.py` | Inventories form fields + types from the live DOM | one `page.evaluate` (self-contained, no Node runtime) |
| `engine/fuzzer/` | `FieldFuzzStrategy` registry (one per field kind) + `DataGenerator` | stdlib |
| `engine/analyzer.py` | Oracle: valid input must not 5xx/console-error; malicious/overflow must reject gracefully | stdlib |
| `engine/correlator.py` | Captured request → FastAPI route table (`ast`) → optional `cx` call-graph enrichment | stdlib `ast`, optional [codeanalyzer](https://github.com/zlexdev/codeanalyzer) |
| `engine/direct_executor.py` | Learns a form's request shape once, replays fuzz cases straight over HTTP | Playwright `APIRequestContext` |
| `engine/reporter.py` | `rich` terminal table + self-contained HTML report | rich |

Everything crosses layer boundaries as frozen Pydantic DTOs (`qai/engine/contracts.py`) —
no raw dicts between layers.

## Safety

Only run against **staging**, never production — the fuzzer submits forms with
malicious/overflow payloads. This MVP does not click destructive buttons or crawl
beyond one form (see `PLAN.md` CUT-list); an autonomous state-graph crawler with a
destructive-action guard is a separate, later effort.

Non-local targets require `--i-own-this-target` (CLI) / `own_target=True` (MCP) before
anything is filled or submitted — otherwise qai only inventories the page's fields.
qai never attempts to solve or bypass a CAPTCHA/anti-bot challenge; it waits out an
automatic Cloudflare JS check and otherwise proceeds honestly (an unresolved
interactive challenge just means an honestly-empty result, not a crash or a bypass).

## Status

MVP = Phases 0–3 from `PLAN.md`. Phase 4 (state-graph crawling, recursion, destructive-
action guard) is intentionally out of scope for this release.

## See also

- [docs/USAGE.md](docs/USAGE.md) — full CLI/library/MCP reference, troubleshooting, safety model
- [docs/REPORTS.md](docs/REPORTS.md) — report formats (JSON/HTML/Markdown) and auto-save
- [PLAN.md](PLAN.md) — MVP phase breakdown (Phases 0–3) and the CUT-list
- [mini-plat.md](mini-plat.md) — the full architecture this project instantiates

## License

MIT
