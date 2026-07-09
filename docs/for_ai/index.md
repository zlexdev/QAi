# qai — AI-agent map

Entry point for an AI agent working in this repo. Read this before opening source
files — it tells you where the answer already lives instead of making you grep
the whole tree.

## Read order

1. **This file** — package map + where each concern lives.
2. **`docs/USAGE.md`** — full CLI flags, library call shape, all MCP tool signatures.
3. **`docs/PLUGINS.md`** — how to write a check plugin (passive or active).
4. **`docs/REPORTS.md`** — JSON/HTML/Markdown report shapes.
5. Only open source directly when a doc is missing, stale, or you need exact
   control flow (e.g. reading `explorer.py`'s BFS loop line by line).

## Package map

| Path | Owns |
|---|---|
| `qai/cli.py` | `qai` CLI entry point (`qai.cli:main`) — argparse, wires flags to `runner`/`api_runner` |
| `qai/mcp_server.py` | MCP server entry point (`qai-mcp` / `qai.mcp_server:main`) — every `@mcp.tool()` (`qa_scan`, `qa_crawl`, `qa_api_scan`, `qa_pipeline_*`, `qa_login_record`, ...) |
| `qai/engine/contracts.py` | Every DTO crossing a layer boundary — frozen Pydantic models. Read this first for any type question (`Finding`, `RunReport`, `CrawlBudget`, `TimeoutConfig`, `SkipReason`, ...) |
| `qai/engine/capture.py` | `CaptureSession` — Playwright + CDP wrapper; navigation, wait/settle logic (`TimeoutConfig`-driven), request/console/DOM capture into `EffectBundle` |
| `qai/engine/modeler.py` | `PageModeler` — inventories form fields + candidate links/buttons from the live DOM (one `page.evaluate`, no Node runtime) |
| `qai/engine/executor.py` | `FormExecutor` — fills + submits a form per a `FuzzPlan` |
| `qai/engine/direct_executor.py` | Learns a form's request shape once, replays fuzz cases straight over HTTP (skips the DOM) |
| `qai/engine/explorer.py` | `Explorer` — BFS crawl over the state graph (dedup by structural DOM hash, budgeted by `CrawlBudget`, domain-scoped via `is_in_scope`/`allowed_domains`) |
| `qai/engine/state.py` | State identity for the crawler — URL normalization, structural DOM hashing, domain-scope checks |
| `qai/engine/fuzzer/` | `FieldFuzzStrategy` registry (one per field kind) + `DataGenerator` producing `FuzzPlan`s |
| `qai/engine/analyzer.py` | The oracle — valid input must not 5xx/console-error; malicious/overflow input must reject gracefully, not crash |
| `qai/engine/correlator.py` | Captured request → source `file:line` via a `ast`-built FastAPI route table, optional `codeanalyzer` (`cx`) enrichment |
| `qai/engine/runner.py` | Orchestrates one full scan/crawl: `run_scan`, `run_crawl` — wires modeler → executor → analyzer → correlator → `RunReport`/`CrawlReport` |
| `qai/engine/api_runner.py` | `run_api_scan` — OpenAPI/GraphQL spec-driven fuzzing straight over HTTP, no browser DOM |
| `qai/engine/apispec/` | OpenAPI/GraphQL spec parsing into `ApiParam`/operation contracts |
| `qai/engine/auth/` | Login macro recording (`record_login`) and replay (`replay_login`) — fills a login form once, returns reusable cookies/bearer token |
| `qai/engine/pipeline/` | The resumable, externally-driven `qa_pipeline_*` session (recon + check stages, one live browser across calls) |
| `qai/engine/plugins/` | Check plugin framework (`Check` ABC, `timeout_s`, `run_with_containment`) + built-in checks (`security_headers`, `idor`, `auth_bypass`) — see `docs/PLUGINS.md` to add one |
| `qai/engine/reporter.py` | `Reporter` — rich terminal table + self-contained HTML report |
| `qai/engine/risk.py` | Destructive-action keyword heuristic (delete/pay/withdraw/...) — gates what the crawler will click |
| `qai/demo_target/` | Tiny FastAPI app with one deliberately-buggy form, used by the README quickstart and tests |

## Core invariants (don't violate these while editing)

- **DTOs at every boundary** — `qai/engine/contracts.py` frozen Pydantic models cross
  every layer; no raw `dict`/`tuple` between modules.
- **`own_target=True` / `--i-own-this-target` gates every real submission** — without
  it, a non-local target is only page-modeled (fields inventoried, nothing filled or
  sent) and active checks are always `SKIPPED`. Never bypass this gate silently.
- **Domain scope is enforced, not advisory** — the crawler only follows the root host
  (+ subdomains if `include_subdomains`, + `CrawlBudget.allowed_domains`); anything
  else is recorded `SkippedPage(reason=off_domain)`, never visited.
- **Timeouts are configurable, not hardcoded** — browser wait budgets live in
  `TimeoutConfig` (`contracts.py`), threaded through `CaptureSession`; don't reintroduce
  a bare `timeout=1234` literal, extend `TimeoutConfig` instead.
- **No AI/paid API calls anywhere in the scan path** — the oracle is deterministic
  (5xx / console-error / DOM error-banner / IDOR / auth-bypass), never an LLM call.

See also: [`../USAGE.md`](../USAGE.md), [`../PLUGINS.md`](../PLUGINS.md),
[`../REPORTS.md`](../REPORTS.md).
