<p align="center">

# QAi

<strong>Autonomous QA fuzzer that finds broken forms &amp; APIs and points at the exact line of code where the bug lives</strong>

</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge" alt="License"></a>
  <a href="pyproject.toml"><img src="https://img.shields.io/badge/python-3.12%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.12+"></a>
  <a href="#deploy--install-as-a-plugin-for-ai-agents-mcp"><img src="https://img.shields.io/badge/MCP-server-6e56cf?style=for-the-badge" alt="MCP server"></a>
  <a href="#deploy--remote-fastapi-service"><img src="https://img.shields.io/badge/REST-API-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="REST API"></a>
  <a href="https://playwright.dev"><img src="https://img.shields.io/badge/browser-Playwright-2ead33?style=for-the-badge&logo=playwright&logoColor=white" alt="Playwright"></a>
</p>

**QAi** is an autonomous QA fuzzer/validator for web forms and APIs — **not a
penetration-testing tool.** Give it a `URL` (+ optionally a repo, an OpenAPI/GraphQL
spec, or a login), it fuzzes every field/operation with valid and malicious input,
catches whatever breaks (server errors, console errors, a DOM error banner a
network-only check would miss), and correlates every finding straight back to
`file:line` — self-hosted, no manual test writing, **no AI/paid APIs required to
run a scan**. A few optional check plugins (IDOR, auth-bypass, security headers)
add security-adjacent coverage on top of the same fuzz engine — a bonus, not the
core of what qai does.

[Full documentation](docs/) · [AI-agent docs](docs/for_ai/)

```
URL → page model / API spec → fuzz matrix + active checks → capture effects
(network+console+DOM) → oracle (5xx/console-error/IDOR/auth-bypass) → correlate
to file:line → report (JSON / HTML / MCP)
```

## Quickstart

```bash
uv sync --extra dev --extra demo
uv run playwright install chromium
```

Try it against the bundled demo target — a tiny FastAPI app with one signup form
whose `name` field has an unguarded server-side length check that a fuzzer's
overflow payload reliably trips:

```bash
uv run uvicorn qai.demo_target.app:app --port 8000 &
uv run qai http://127.0.0.1:8000 --repo qai/demo_target --html report.html
```

Open `report.html` — a self-contained dark-themed report with a clickable
`qai/demo_target/app.py:LINE` next to the finding. See [docs/USAGE.md](docs/USAGE.md)
for every CLI flag, library call, and MCP tool signature.

## Why qai

qai's core loop is QA validation, not security testing: the oracle's question is
"does this input crash or break the app", the same thing a hand-written end-to-end
test suite checks, just generated and run automatically instead of typed out by
hand. The IDOR/auth-bypass/security-header checks are optional plugins layered on
the same fuzz engine — useful, but a bonus on top of the bug-finding core, not
what qai primarily is.

| | qai | Playwright/Cypress (hand-written E2E) | Burp Suite / ZAP |
|---|---|---|---|
| Finds bugs without writing test cases | yes — fuzz-generated | no — you write every case | no — not its job |
| Bug → exact `file:line` in your repo | yes | no | no |
| Native MCP server (agent-drivable) | yes | no | no |
| OpenAPI/GraphQL spec-driven fuzzing | yes | no | yes |
| Optional security checks (IDOR, auth-bypass) | yes — opt-in plugins | no | yes — that's the whole point |
| Self-hosted, no AI/paid API calls | yes | yes | yes |
| Free & open source | yes | yes | ZAP: yes / Burp: no |

The file:line correlation and MCP-native design are the two things neither a
hand-written test suite nor a general pentest scanner does: an agent (Claude Code,
Cursor, …) can run a scan *and* open the exact file the bug lives in, in the same
session.

## Contents

- [CLI features](#stability-parallel-tabs-direct-request-fuzzing-har)
- [Use as a library](#use-as-a-library)
- [MCP server for AI agents](#deploy--install-as-a-plugin-for-ai-agents-mcp)
- [Remote FastAPI service](#deploy--remote-fastapi-service)
- [How it works](#how-it-works)
- [Safety](#safety)

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

## Deploy — install as a plugin for AI agents (MCP)

qai ships an MCP (Model Context Protocol) server, so any MCP-speaking agent — Claude
Code, Claude Desktop, Cursor, a custom agent harness — can call it as a tool instead of
you running the CLI by hand. Nine tools are exposed (see
[docs/USAGE.md](docs/USAGE.md#mcp-server-for-ai-agents) for full signatures):

| Tool | What it does |
|---|---|
| `qa_scan` | Fuzz one page's forms, return a JSON `RunReport`. Optional `plugins=[...]` runs check plugins (e.g. `security_headers`, `idor`, `auth_bypass`) alongside the fuzz oracle; `login_macro=` replays a saved login first. |
| `qa_scan_html` | Same as `qa_scan`, plus writes a self-contained dark-themed HTML report. |
| `qa_crawl` | BFS-discover same-origin pages from a root URL, fuzz every form found. |
| `qa_api_scan` | Parse an OpenAPI/GraphQL spec and fuzz every operation straight over HTTP — same `RunReport` shape, no DOM needed. |
| `qa_login_record` | Record a login once (fills the form, reads back cookies/bearer token) and return a reusable `LoginMacro`. |
| `qa_pipeline_start` | Open a resumable, externally-driven pipeline (recon + check stages) — one live browser session across calls. `own_target=True` is required for an `ACTIVE` check stage (e.g. `idor`) to actually run. |
| `qa_pipeline_step` | Run or skip exactly one stage; optionally inject an `AgentDirective` first. |
| `qa_pipeline_report` | Project the session's current findings as a `RunReport`, without tearing it down. |
| `qa_pipeline_abort` | Free the live browser and delete the session. |

Active checks (`idor`, `auth_bypass`) fire real extra requests and are gated by the
same `own_target`/safe-mode rule as fuzzing itself — omit `own_target=True` and they're
always `SKIPPED`, never run, against a target you haven't confirmed you own.

### 1. Install

```bash
git clone https://github.com/zlexdev/QAi.git
cd QAi
uv sync --extra mcp
uv run playwright install chromium
```

There's no PyPI package yet — install from a local clone (above) or straight from git:

```bash
uv tool install "qai[mcp] @ git+https://github.com/zlexdev/QAi.git"
uv tool run playwright install chromium   # once, after install
```

`uv tool install` puts `qai` and `qai-mcp` on your `PATH` globally, isolated in their
own venv — no need to activate anything before pointing an agent at them.

### 2. Register it with an agent

**Claude Code** (this CLI) — one command, from the repo root:

```bash
claude mcp add qai -- uv run --directory /absolute/path/to/QAi qai-mcp
# or, if installed with `uv tool install`:
claude mcp add qai -- qai-mcp
```

Use `--scope user` to make it available in every project, not just this one:

```bash
claude mcp add qai --scope user -- qai-mcp
```

**Claude Desktop** — add to `claude_desktop_config.json`
(`%APPDATA%\Claude\claude_desktop_config.json` on Windows,
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS):

```json
{
  "mcpServers": {
    "qai": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/QAi", "qai-mcp"]
    }
  }
}
```

**Any other MCP client** — the server speaks stdio, so the shape is always
`{"command": ..., "args": [...]}`; point it at `qai-mcp` (if `uv tool install`ed) or
`uv run --directory <repo> qai-mcp` (running from a clone). No network port, no auth
token — it's a local subprocess the agent's own harness spawns and owns.

### 3. Safety when handing an agent this tool

`own_target=True` gates real submissions exactly like `--i-own-this-target` does on the
CLI — an agent can call `qa_scan`/`qa_crawl` against any URL and safely get a read-only
page model back; it must explicitly pass `own_target=True` to actually fuzz a non-local
host. Don't grant `own_target=True` by default in an agent's system prompt/tool config
unless every target it might be pointed at is one you own — see [Safety](#safety) below.

### 4. Examples

These are real tool calls against the bundled demo target
(`uv run uvicorn qai.demo_target.app:app --port 8000`) — the JSON is abbreviated for
readability but the shapes and values are unmodified from an actual run.

**Plain fuzz scan** — no plugins, matches CLI-only behaviour byte-for-byte except the
always-present `plugin_findings: []`:

```jsonc
// call: qa_scan(url="http://127.0.0.1:8000", repo_path="qai/demo_target")
{
  "run_id": "5c77053f29de",
  "forms_scanned": 1,
  "cases_executed": 71,
  "findings": [
    {
      "severity": "high",
      "kind": "server_error",
      "detail": "POST http://127.0.0.1:8000/signup -> 500 on intent=overflow value='AAA...'",
      "source_location": { "file": "app.py", "line": 40, "symbol": "signup" }
    },
    { "severity": "medium", "kind": "console_error", "detail": "Failed to load resource: ... 500 ..." }
  ],
  "plugin_findings": []
}
```

**Scan + check plugin** — same call, `plugins=["security_headers"]` added, runs the
fuzz oracle and the header check in one pass:

```jsonc
// call: qa_scan(url="http://127.0.0.1:8000", repo_path="qai/demo_target",
//               plugins=["security_headers"])
{
  "run_id": "e635378e46d6",
  "forms_scanned": 1,
  "cases_executed": 71,
  "findings": [ /* same 500-on-overflow finding as above */ ],
  "plugin_findings": [
    { "plugin": "security_headers", "category": "missing_csp", "severity": "low",
      "title": "Missing content-security-policy response header" },
    { "plugin": "security_headers", "category": "missing_x_frame_options", "severity": "low",
      "title": "Missing x-frame-options response header" },
    { "plugin": "security_headers", "category": "missing_hsts", "severity": "low",
      "title": "Missing strict-transport-security response header" },
    { "plugin": "security_headers", "category": "missing_x_content_type_options", "severity": "low",
      "title": "Missing x-content-type-options response header" }
  ]
}
```

**Screenshot the page qai scanned** — real output from an actual run:

```jsonc
// call: qa_scan(url="http://127.0.0.1:8000", repo_path="qai/demo_target", screenshot=true)
{
  "run_id": "849c2cf13a41",
  "forms_scanned": 1,
  "findings": [ /* 2 findings, same overflow bug */ ],
  "screenshot_path": "qai-reports/screenshots/849c2cf13a41.png"
}
// -> Read that path directly (Claude Code, or any agent that can open images)
```

**Active checks** — IDOR + auth-bypass replay, gated by `own_target` (never fire
without it, see [Safety](#safety)):

```jsonc
// call: qa_scan(url="http://127.0.0.1:8000", repo_path="qai/demo_target",
//               plugins=["idor", "auth_bypass"], own_target=true)
{
  "plugin_findings": [
    { "plugin": "idor", "category": "idor_candidate", "severity": "medium",
      "title": "GET /api/items/{id} returned 200 for an id never linked from the page" },
    { "plugin": "auth_bypass", "category": "auth_bypass", "severity": "high",
      "title": "GET /api/admin/stats returned 200 with no auth header at all" }
  ]
}
```

**Spec-driven API scan** — fuzz an OpenAPI/GraphQL spec straight over HTTP, no DOM:

```jsonc
// call: qa_api_scan(spec={"kind": "openapi", "raw": "<contents of openapi.json>"},
//                    base_url="http://127.0.0.1:8000", own_target=true)
{ "run_id": "...", "forms_scanned": 2, "findings": [ /* per-operation findings */ ] }
```

**Record a login once, replay it on every future scan**:

```jsonc
// call: qa_login_record(login_url="http://127.0.0.1:8000/login",
//                        username="admin", password="secret")
{
  "macro": { "login_url": "...", "username_selector": "#username", "...": "..." },
  "auth_result": { "authenticated": true, "cookies": [ { "name": "session", "...": "..." } ] }
}
// save `macro` to a file, then: qa_scan(url="...", login_macro=<saved macro>)
```

**Authenticated scan** — cookies injected before any navigation:

```jsonc
// call: qa_scan(url="https://app.internal/dashboard", repo_path="/repos/app",
//               cookies=[{"name": "session", "value": "abc123", "domain": "app.internal"}],
//               own_target=true)
```

**HTML report for a human reader**:

```jsonc
// call: qa_scan_html(url="http://127.0.0.1:8000", repo_path="qai/demo_target",
//                     out_path="report.html")
{ "run_id": "...", "ok": false, "findings_count": 2, "html_report": "C:\\...\\report.html" }
```

**Crawl mode** — BFS-discover pages, fuzz every form found:

```jsonc
// call: qa_crawl(url="http://127.0.0.1:8000", repo_path="qai/demo_target",
//                 max_depth=2, max_actions=50)
{ "run_id": "...", "states_visited": 3, "pages": [ /* one RunReport per page with a form */ ] }
```

**Driven pipeline** — step-by-step, inspecting output and injecting context between
stages (this is the sequence a Claude Code session actually ran):

```jsonc
// 1) qa_pipeline_start(url="http://127.0.0.1:8000", repo_path="qai/demo_target")
{ "session_id": "a4b10b47...", "cursor": 0, "steps": [
  { "name": "recon", "status": "pending" }, { "name": "security_headers", "status": "pending" }
]}

// 2) qa_pipeline_step(session_id="a4b10b47...")            -> runs "recon"
{ "cursor": 1, "steps": [{ "name": "recon", "status": "done" }, { "name": "security_headers", "status": "pending" }] }

// 3) qa_pipeline_step(session_id="a4b10b47...", inject={"notes": "focus on headers"})
{ "cursor": 2, "steps": [{ "status": "done" }, { "status": "done" }],
  "last_step_output": [ /* the same 4 security_headers findings as above */ ] }

// 4) qa_pipeline_report(session_id="a4b10b47...")          -> RunReport-shaped projection
{ "plugin_findings": [ /* 4 findings */ ] }

// 5) qa_pipeline_abort(session_id="a4b10b47...")           -> frees the browser
{ "ok": true }
```

**Recon-only pipeline** (skip the check stage entirely):

```jsonc
// call: qa_pipeline_start(url="http://127.0.0.1:8000", plugins=[])
// -> steps: [{"name": "recon", "status": "pending"}]   (no security_headers stage)
```

**Skipping a stage mid-pipeline** instead of running it:

```jsonc
// call: qa_pipeline_step(session_id="a4b10b47...", skip=true)
// -> cursor advances, that stage's status becomes "skipped", no side effects run
```

## Deploy — remote FastAPI service

For driving qai over the network instead of a local MCP subprocess — put it on a
server and hit it with `curl`/any HTTP client. Same underlying engine as the MCP
tools above (`run_scan`, `run_crawl`, `run_api_scan`, `record_login`, the
pipeline session store); this is just a second transport, not a second engine.

### Run it locally

```bash
uv sync --extra api
export QAI_API_KEY=$(openssl rand -hex 32)
uv run qai-api          # listens on 0.0.0.0:8000
```

```bash
curl -X POST http://127.0.0.1:8000/v1/scan \
  -H "X-API-Key: $QAI_API_KEY" -H "Content-Type: application/json" \
  -d '{"url": "http://127.0.0.1:8000", "repo_path": "qai/demo_target"}'
# -> {"job_id": "...", "status": "pending"}
curl http://127.0.0.1:8000/v1/jobs/<job_id> -H "X-API-Key: $QAI_API_KEY"
# -> {"job_id": "...", "status": "done", "result": { ...RunReport... }}
```

Scans/crawls/API-scans are long-running, so every submit endpoint returns `202` +
a `job_id` immediately; poll `GET /v1/jobs/{id}` for the result. Pipeline sessions
(`/v1/pipeline/*`) mirror the MCP `qa_pipeline_*` tools one-to-one and don't need
polling — each call returns the current state directly.

| Endpoint | Mirrors MCP tool |
|---|---|
| `POST /v1/scan` | `qa_scan` |
| `POST /v1/crawl` | `qa_crawl` |
| `POST /v1/api-scan` | `qa_api_scan` |
| `POST /v1/login-record` | `qa_login_record` |
| `GET /v1/jobs/{id}` | — poll result of any of the above |
| `POST /v1/pipeline/start` | `qa_pipeline_start` |
| `POST /v1/pipeline/{id}/step` | `qa_pipeline_step` |
| `GET /v1/pipeline/{id}/report` | `qa_pipeline_report` |
| `DELETE /v1/pipeline/{id}` | `qa_pipeline_abort` |
| `GET /healthz` | — unauthenticated liveness check |

Every route except `/healthz` requires an `X-API-Key` header matching `QAI_API_KEY`
(constant-time compared). Run single-worker (`qai-api` always does) — job/session
state is in-process, so a multi-worker run would silently split jobs across
processes.

Interactive API reference (built from the live OpenAPI schema, [Scalar](https://scalar.com)):
open `http://127.0.0.1:8000/scalar` (or `https://<your-domain>/scalar` once deployed).

### REST examples

Same demo target as the MCP examples above
(`uv run uvicorn qai.demo_target.app:app --port 8000`); `$KEY` is `$QAI_API_KEY`.

**Crawl** — BFS-discover pages, fuzz every form found:

```bash
curl -X POST http://127.0.0.1:8000/v1/crawl -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"url": "http://127.0.0.1:8000", "repo_path": "qai/demo_target", "max_depth": 2, "max_actions": 50}'
# -> {"job_id": "...", "status": "pending"}  — poll GET /v1/jobs/{id} for the CrawlReport
```

**Spec-driven API scan** — fuzz an OpenAPI/GraphQL spec straight over HTTP, no DOM:

```bash
curl -X POST http://127.0.0.1:8000/v1/api-scan -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d "{\"spec\": $(cat qai/demo_target/openapi.json | jq -Rs .), \"base_url\": \"http://127.0.0.1:8000\", \"own_target\": true}"
```

**Record a login once, replay it on every future scan**:

```bash
curl -X POST http://127.0.0.1:8000/v1/login-record -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"login_url": "http://127.0.0.1:8000/login", "username": "admin", "password": "secret"}'
# -> {"job_id": "...", "status": "pending"}
curl http://127.0.0.1:8000/v1/jobs/<job_id> -H "X-API-Key: $KEY"
# -> result: {"macro": {...LoginMacro...}, "auth_result": {"authenticated": true, "cookies": [...]}}
# save `macro` from the result, then pass it as "login_macro" on a later /v1/scan or /v1/crawl call
```

**Driven pipeline** — step-by-step, inspecting output and injecting context between stages:

```bash
SID=$(curl -s -X POST http://127.0.0.1:8000/v1/pipeline/start -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"url": "http://127.0.0.1:8000", "repo_path": "qai/demo_target"}' | jq -r .session_id)

curl -X POST http://127.0.0.1:8000/v1/pipeline/$SID/step -H "X-API-Key: $KEY" -H "Content-Type: application/json" -d '{}'
# -> runs "recon"; steps[0].status becomes "done"

curl -X POST http://127.0.0.1:8000/v1/pipeline/$SID/step -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"inject": {"notes": "focus on headers"}}'
# -> runs "security_headers"; last_step_output carries its findings

curl http://127.0.0.1:8000/v1/pipeline/$SID/report -H "X-API-Key: $KEY"
# -> RunReport-shaped projection of the session so far, doesn't tear it down

curl -X DELETE http://127.0.0.1:8000/v1/pipeline/$SID -H "X-API-Key: $KEY"
# -> {"ok": true}, frees the browser and deletes the session
```

### Deploy to a server with a domain + TLS

```bash
git clone https://github.com/zlexdev/QAi.git && cd QAi
bash scripts/install.sh
```

Prompts once for a domain (must already point an A/AAAA record at the host) and
generates/caches an API key in `~/.qai.conf`; from there it's idempotent — re-run
after a `git pull` to pick up an update. It installs system deps, syncs the `api`
extra, provisions a `qai-api` systemd service, and fronts it with nginx + a
Let's Encrypt cert via certbot. `bash scripts/install.sh --dry-run` prints every
step without touching the host.

On a shared host, cap the service's memory so one heavy scan (Chromium) can't
starve sibling processes: `QAI_MEMORY_MAX=512M bash scripts/install.sh` (default
`512M`, cached in `~/.qai.conf` like the domain/port/API key — the systemd unit
gets `MemoryMax`/`MemorySwapMax=0`, so a scan gets OOM-killed by its own cgroup
instead of taking the host down).

Full install-phase breakdown, config reference, operating/update commands,
memory-cap sizing guidance, and TLS/DNS troubleshooting: [docs/DEPLOY.md](docs/DEPLOY.md).

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

`engine/fuzzer/strategies.py`'s pattern-violation case (`FuzzIntent.SCHEMA_VIOLATION` —
find a value that provably fails a field's JSON-schema `pattern`, then assert the API
rejects it) ports the "negative testing" idea from
[Schemathesis](https://github.com/schemathesis/schemathesis) (MIT) — same concept
(prove a value violates the schema, expect a graceful rejection), implemented here
with a stdlib-only `re`-verified heuristic instead of Schemathesis's
Hypothesis-driven schema negation.

## Safety

Only run against **staging**, or your own targets — the fuzzer submits forms with
malicious/overflow payloads and, with `plugins=["idor","auth_bypass"]`, fires real
mutated replay requests. Links/buttons matching a destructive keyword are never
clicked during a crawl unless explicitly allow-listed (`--allow-destructive` /
`allow_destructive=[...]`) — see `qai.engine.risk` for the heuristic.

Non-local targets require `--i-own-this-target` (CLI) / `own_target=True` (MCP) before
anything is filled, submitted, or actively replayed — otherwise qai only inventories
the page's fields and active checks are always `SKIPPED`. qai never attempts to solve
or bypass a CAPTCHA/anti-bot challenge; it waits out an automatic Cloudflare JS check
and otherwise proceeds honestly (an unresolved interactive challenge just means an
honestly-empty result, not a crash or a bypass).

## See also

- [docs/USAGE.md](docs/USAGE.md) — full CLI/library/MCP reference, troubleshooting, safety model
- [docs/DEPLOY.md](docs/DEPLOY.md) — remote FastAPI service deploy guide (install phases, config reference, shared-host memory sizing, TLS troubleshooting)
- [docs/PLUGINS.md](docs/PLUGINS.md) — writing a check plugin (passive or active)
- [docs/REPORTS.md](docs/REPORTS.md) — report formats (JSON/HTML/Markdown) and auto-save
- [docs/for_ai/](docs/for_ai/) — condensed package map for an AI coding agent working in this repo

## Contributing

```bash
git clone https://github.com/zlexdev/QAi.git && cd QAi
uv sync --extra dev --extra demo --extra api
uv run playwright install chromium
uv run pytest
uv run ruff check . && uv run mypy qai
```

PRs go against `master`; CI expectation is ruff + mypy (`strict`) + pytest all green.
New engine-level types go in `qai/engine/contracts.py` as frozen Pydantic models — no
raw `dict`/`tuple` crossing a layer boundary. Sync the relevant `_MODULE_AUTO.md` after
touching a package (see [docs/for_ai/](docs/for_ai/) for the doc map).

## Community

Use [issues](https://github.com/zlexdev/QAi/issues) for bugs and feature requests.

<a href="https://github.com/Asmin963"><img src="https://github.com/Asmin963.png" width="48" height="48" style="border-radius:50%" alt="Asmin963"></a>

## License

[MIT](LICENSE) © 2026 Asmin963
