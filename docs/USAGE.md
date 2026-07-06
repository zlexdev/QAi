---
title: QAi — usage guide
---

# QAi — usage guide

QAi runs one core loop against a target URL:

```
URL → page model (fields+types) → fuzz matrix per form → capture effects
(network+console+DOM) → oracle (5xx/console-error/DOM-banner) → correlate to file:line → report
```

It ships three ways to drive that loop: a **CLI** (`qai`), a **Python library**
(`qai.engine.runner.run_scan`), and an **MCP server** (`qai-mcp`) for AI agents.

## Install

```bash
uv sync --extra dev --extra demo   # +mcp if you want the MCP server
uv run playwright install chromium
```

Optional: install [codeanalyzer](https://github.com/zlexdev/codeanalyzer) (`cx`) and put
it on `PATH` — the code correlator uses it to enrich findings with the handler's
call-graph (callees, field writes). Without it, correlation still works (route → file:line
via `ast`), just without the extra call-graph context.

## CLI reference

```
qai <url> [options]
```

| Flag | Default | What it does |
|---|---|---|
| `<url>` | — | Target to scan (positional, required) |
| `--repo PATH` | none | Path to the target's source repo — enables `file:line` correlation |
| `--json PATH` | none | Write the machine-readable `RunReport` as JSON (in addition to the auto-saved copy) |
| `--html PATH` | none | Write the self-contained dark-themed HTML report |
| `--report-dir DIR` | `qai-reports` | Where the auto-saved `.json`/`.md` report goes every run — see [REPORTS.md](REPORTS.md) |
| `--no-auto-report` | off | Disable the automatic `.json`/`.md` report |
| `--headed` | off | Run the browser headed (visible window) instead of headless |
| `--verbose` | off | Debug-level structlog output |
| `--parallel N` | `1` | Fan fuzz cases across N concurrent worker sessions ("tabs"), each tagged `tab-<i>` |
| `--har DIR` | none | Record one `.har` per tab into this directory |
| `--direct` | off | After one baseline UI submit per form, fuzz the rest straight over HTTP |
| `--i-own-this-target` | off | Required to actually submit anything against a **non-local** host |
| `--crawl` | off | Discover same-origin pages (BFS) and fuzz every form found, not just `<url>` |
| `--max-depth N` | `2` | Crawl: max BFS depth |
| `--max-actions N` | `50` | Crawl: max links/buttons followed |
| `--wall-clock S` | `180` | Crawl: overall time budget in seconds |
| `--allow-destructive SELECTOR` | none | Repeatable — allow clicking a specific destructive-looking selector during a crawl |
| `--cookie DOMAIN:NAME=VALUE` | none | Repeatable — inject an auth cookie before any navigation, so a scan can reach pages behind a login wall. Each cookie's own domain decides which requests carry it, so a separate auth/SSO subdomain's cookie can be listed alongside the main target's: `--cookie .example.com:session=abc --cookie sso.example.com:token=xyz` |

Exit code: `0` if no findings, `2` if findings exist, `1` on a `QaiError` (bad URL,
missing repo path, capture failure after retry).

### The safety gate — read this before pointing QAi at anything

Any URL whose host is **not** `localhost` / `127.0.0.1` / `::1` runs in **safe_mode**
unless you pass `--i-own-this-target`:

- safe_mode: QAi navigates, models the page (inventories every form + field + type),
  and stops. **No field is ever filled. No request is ever submitted.**
- with `--i-own-this-target`: QAi runs the full pipeline — fills every form with the
  fuzz matrix (valid / empty / boundary / overflow / malicious / unicode) and submits it.

This exists so that `qai https://some-domain.com` can never accidentally fuzz
production infrastructure you don't control. Passing `--i-own-this-target` is *you*
asserting you're authorized to fuzz that host — QAi does not and cannot verify
ownership; the flag is a deliberate-action gate, not a security boundary. **Only use it
against staging/targets you actually own or have explicit permission to test.**

QAi will also never attempt to solve, click through, or bypass a CAPTCHA / interactive
anti-bot challenge. It waits (up to ~15s) for an *automatic* Cloudflare JS check to clear
on its own, then proceeds — if an interactive challenge is still showing, the scan
proceeds honestly against whatever's on screen (usually meaning zero forms found, not
a crash or a fabricated success).

### Examples

Local dev loop (no flag needed — localhost is exempt from safe_mode):

```bash
uv run uvicorn qai.demo_target.app:app --port 8000 &
uv run qai http://127.0.0.1:8000 --repo qai/demo_target --html report.html
```

Recon only, on a site you don't (yet) own — see what forms exist, submit nothing:

```bash
uv run qai https://example.com --json recon.json
```

Full authorized scan on your own staging, 5 parallel tabs, HAR capture, direct-request
fast path:

```bash
uv run qai https://staging.example.com --repo ~/code/example --i-own-this-target \
  --parallel 5 --har ./har --direct --html report.html --json report.json
```

## Feature reference

### Parallel tabs (`--parallel N`)

Fuzz cases for all forms on the page are partitioned round-robin across `N`
independent worker sessions. Each worker owns its own `BrowserContext`+page (**not** a
separate Chromium process — all tabs in one `run_scan`/`run_crawl` call share a single
launched browser via a `BrowserPool`) and is tagged `tab-0`, `tab-1`, … — every
`Finding` and its underlying `EffectBundle` carry that `tab_id`, so you can stitch a
tab's console log / requests back into one story later (e.g. when grepping a `.har`
for the same tab).

Cost/benefit: more tabs = more wall-clock throughput (measured: 26 cases against the
demo target, 60s at 1 tab → 24.6s at 3 tabs), but each tab is still a real page/JS
context inside the shared browser. Start at 3–5 and watch resource usage before going
higher.

### Direct-request fast path (`--direct`)

For each form, QAi runs exactly one baseline (valid-intent) case through the normal
UI (fill + click), the same as always. If that baseline's request has a
`application/x-www-form-urlencoded` body where every field's value is unique and
traceable 1:1 back to a form field, QAi **learns a `RequestTemplate`** from it. Every
remaining fuzz case for that form then fires straight over HTTP via the browser
context's cookie jar (`context.request.fetch(...)`) — no DOM interaction at all.

Why this matters: browsers enforce `maxlength`, `type="number"`, `type="range"` etc.
at the DOM level, so `page.fill()` silently truncates/rejects payloads that don't fit
those constraints — even after QAi strips them via JS, some browser-native input
types (like `range`) still refuse arbitrary strings through `fill()`. The direct path
sidesteps this: the *server* sees exactly what QAi sends, byte for byte.

When it can't learn a template (multipart forms, JSON bodies, CSRF tokens, duplicate
field values, hashed/computed fields) it silently falls back to the UI path for that
form — you always get results, just not always the speed-up.

### Crawl mode (`--crawl`)

Discovers same-origin pages reachable from `<url>` (BFS, shallow-first) and fuzzes
every form found along the way, instead of only the one page you pointed it at.

- **State identity** is (normalized URL, structural DOM hash) — a hash of tags/roles/
  hierarchy only, never text or timestamps, so a paginated list or a live clock doesn't
  look like infinitely many new states.
- **Replay**: reaching a state found deep in the crawl means re-navigating from the
  root and replaying the recorded action path (links replay via direct navigation;
  SPA-only button clicks replay via click) — a URL alone can't identify SPA in-memory
  state.
- **Budgets** stop the crawl: `--max-depth`, `--max-actions`, `--wall-clock`. Hitting
  one is reported as `budget_exhausted_by` in the JSON report, not a silent truncation.
  `--max-actions` counts pages actually **visited** (not merely discovered — duplicate
  nav/footer/mobile-menu links to the same URL are deduped before they ever cost budget).
  ⚠️ `--wall-clock` currently bounds only the discovery (BFS) phase, not the fuzz pass
  run afterward on every discovered page with a form — a crawl that finds many
  form-bearing pages can still take much longer overall than `--wall-clock` alone
  suggests. Budget the fuzz phase yourself via `--max-actions` (fewer pages = less
  total fuzz time) until an overall time cap lands.
- **Trap detection**: a state whose DOM hash repeats `CrawlBudget.trap_repeat_limit`
  times (default 3) stops being expanded further — guards against infinite
  calendars/paginations that would otherwise exhaust the action budget on one trap.
- **Destructive-action guard**: links/buttons whose visible text matches a keyword
  heuristic (EN+RU: delete/pay/withdraw/transfer/удалить/оплатить/вывести/перевести/...)
  are never clicked — see `CrawlReport.skipped_destructive`. This is a heuristic, not a
  security guarantee; review it yourself before assuming nothing destructive was
  touched. Use `--allow-destructive SELECTOR` (repeatable) to explicitly permit one.
- Each discovered page with a form gets its own `RunReport` under `CrawlReport.pages`;
  `CrawlReport.findings` flattens all of them for convenience.

```bash
uv run qai https://staging.example.com --repo ~/code/example --i-own-this-target \
  --crawl --max-depth 3 --max-actions 100 --wall-clock 300 --json crawl-report.json
```

### HAR recording (`--har DIR`)

One `.har` file per tab, named `<run_id>-tab-<i>.har`. Load it into any HAR viewer
(Chrome DevTools' Network tab → import, or `har-viewer` CLIs) to inspect every request
QAi's browser made, byte for byte — useful when a finding's `detail` truncation (see
below) isn't enough context.

### The oracle: what counts as a bug

| Signal | Source | Finding kind |
|---|---|---|
| `5xx` response | network capture | `server_error` (severity: high) |
| Connection/DNS failure | network capture | `network_fail` (medium) |
| Valid input rejected (`4xx`) | network capture | `invariant` (low) |
| `console.error` / uncaught JS exception | Playwright console/pageerror events | `console_error` (medium) |
| New `[role="alert"]` / `.error` / `[aria-invalid="true"]` text after the action | DOM diff, no network signal needed | `dom_error` (medium) |

Rule of thumb: `valid` input must never produce any of the above; `malicious`/
`overflow` input must be rejected **gracefully** (a clean 4xx or a DOM validation
message) — a `500` or a silent 200-swallow on a malicious payload is exactly the bug
class this tool exists to catch.

Findings are attributed to a request only when that request's HTTP method matches
the form's own `method` attribute (default `POST`) — this filters out unrelated
background traffic (nav-link prefetches, analytics beacons) that a time-windowed
capture would otherwise misattribute to the fuzz action.

**Malicious payload catalogue** (`qai/engine/fuzzer/strategies.py`): SQL injection,
XSS, path traversal (raw + URL-encoded + Windows-style), template injection (`${{}}`/
`{{}}`/`#{}`/`<%= %>`), NoSQL operator injection, OS command injection, CRLF/header
injection, null-byte truncation, LDAP injection, plus numeric edge cases (32/64-bit
integer boundaries, `NaN`/`Infinity`, leading-zero octal confusion, hex/scientific
notation a strict int field should reject). Every field gets the full text-payload set;
number fields get the numeric set on top of their min/max-derived boundary cases.

### Reports

- **Terminal**: a `rich` table, severity-colored, sorted high→low.
- **Auto-saved every run**: `.json` + `.md` under `--report-dir` (default
  `./qai-reports/<run_id>.{json,md}`) — no flag needed; disable with `--no-auto-report`.
  Full breakdown in [REPORTS.md](REPORTS.md).
- **`--json`**: the full `RunReport` (`run_id`, `forms_scanned`, `cases_executed`,
  `tabs_used`, `har_paths`, `safe_mode`, `findings[]`) — feed this to CI.
- **`--html`**: a self-contained dark-themed page (inline CSS, no external assets) with
  clickable `file:line` next to each finding that has a `source_location`.

## Library usage

```python
import asyncio
from qai.engine.runner import run_scan

async def main():
    report = await run_scan(
        "http://127.0.0.1:8000",
        repo_path="qai/demo_target",
        headless=True,
        max_parallel=3,
        har_dir="./har",
        safe_mode=False,      # True = model only, never fill/submit
        direct_mode=True,
    )
    for f in report.findings:
        print(f.severity, f.kind, f.detail, f.source_location)

asyncio.run(main())
```

`run_scan` never enforces the CLI's host-based safe_mode default — that gate lives in
`qai/cli.py` and `qai/mcp_server.py`. Calling `run_scan` directly, you are responsible
for setting `safe_mode` yourself when scanning anything you don't own.

## MCP server (for AI agents)

```bash
uv sync --extra mcp
uv run qai-mcp
```

Point your MCP client (Claude Code, another agent harness) at `qai-mcp` over stdio.
Three tools:

- **`qa_scan(url, repo_path=None, headless=True, parallel=1, har_dir=None, own_target=False, direct_mode=False, cookies=None)`**
  → JSON `RunReport`.
- **`qa_scan_html(url, repo_path=None, out_path="qai-report.html", headless=True, parallel=1, own_target=False)`**
  → JSON summary + a written HTML report path.
- **`qa_crawl(url, repo_path=None, headless=True, max_depth=2, max_actions=50, wall_clock_seconds=180, allow_destructive=None, parallel=1, own_target=False, direct_mode=False, cookies=None)`**
  → JSON `CrawlReport` (BFS-discovered pages, each fuzzed; see Crawl mode above).

`cookies` is a list of dicts (`{"name": ..., "value": ..., "domain": ..., "path": "/", "secure": false, "http_only": false, "same_site": "Lax"}` — only `name`/`value`/`domain` required), injected before any navigation so the scan/crawl can reach pages behind a login wall. Each cookie's own `domain` decides which requests carry it, so a separate auth/SSO subdomain's cookie can be listed alongside the main target's.

`own_target` is the MCP equivalent of `--i-own-this-target` — an agent can call
`qa_scan`/`qa_crawl` against any URL and safely get a read-only page model back; it
must explicitly pass `own_target=True` to get a real fuzz run against a non-local host.
This means an agent can be handed these tools without a human reviewing every call —
the worst case of a mis-aimed scan is an inventory, not a payload storm against a
stranger's site.

Example MCP client config entry (stdio transport):

```json
{
  "mcpServers": {
    "qai": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/QAi-agent", "qai-mcp"]
    }
  }
}
```

## Troubleshooting

- **Findings truncated mid-payload** (`'AAAA...(+1920 chars)'`) — intentional: overflow
  cases can be 100k characters; both the `detail` string and the stored
  `request_body` are truncated to keep reports/logs readable. The full value is not
  recoverable from the report by design — re-run with `--har` if you need the exact
  bytes sent.
- **`UnicodeEncodeError` on Windows** — fixed as of this release: the CLI forces UTF-8
  on stdout/stderr at startup regardless of the terminal's codepage. If you still hit
  this, you're likely calling `Reporter` directly without going through `qai.cli.main`.
- **A JS-heavy page (Next.js/React) reports 0 forms it clearly has** — QAi waits for
  `networkidle` *and* for the DOM element count to stop growing (handles delayed
  hydration), capped at a few seconds. Extremely slow-hydrating pages may still race
  this; there's currently no manual override for the wait budget.
- **A `type="range"` / other exotic input isn't fuzzed with non-numeric payloads** —
  by design for `range`: it's modeled as a numeric field (min/max/step aware) and its
  native type is swapped to `text` before fill so any fuzz string can be typed; other
  truly custom controls (web components, canvas-based inputs) are not modeled at all —
  QAi only sees native `<input>/<select>/<textarea>` elements.
- **`cx` not found** — correlation still works via the `ast`-based route table; you
  just don't get the extra call-graph enrichment (callees/field-writes) on each
  `source_location`.

## What QAi does *not* do (by design)

- No multi-page crawling / state-graph exploration (see `PLAN.md` CUT-list — this is
  a deliberately separate, larger effort, not silently attempted here).
- No CAPTCHA solving or anti-bot bypass, ever.
- No destructive-click guard (because there's no autonomous clicking beyond the one
  form you pointed it at) — don't point QAi at a page whose only form is a "Delete
  account" button.
- No AI/LLM calls anywhere in the pipeline — every decision (field typing, fuzz
  values, oracle, correlation) is deterministic code.
