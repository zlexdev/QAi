# qai.engine.pipeline

Externally-driven, resumable pipeline (Design 2) — the *external* MCP caller (e.g.
Claude Code) drives one stage at a time: inspect step N's output, inject context,
skip/continue, configure step N+1. qai runs no internal LLM; it supplies the mechanism,
the caller supplies the judgment (see the plan's `00-overview.md` Decision B).

## Shape

- `PentestContext` (`contracts.py`) — mutable `@dataclass(slots=True)` threaded through
  every `Stage.__call__`. Every field is JSON-serializable so `SessionStore` can persist
  it between MCP tool calls (each of which is otherwise stateless).
- `Stage` (`contracts.py`) — one class, one `async __call__(ctx) -> ctx`. New behaviour
  is a new stage, never an edit to an existing one.
- `Pipeline` (`pipeline.py`) — holds the fixed stage list + cursor; `step()` runs or
  skips exactly one stage; `to_state()` projects a `PipelineState` for the MCP caller.
- `SessionStore` (`session.py`) — persists `PentestContext`/`StepInfo`/cursor to SQLite
  so a session survives an MCP server restart. The live `BrowserPool`/`Page` itself
  cannot be persisted (it's a live Playwright process handle) — see the module's own
  docstring on `SqliteSessionStore` and the plan's `05-risks.md` R-3 for the
  re-open-on-resume behavior this implies.

## Layering

Imports `qai.engine.plugins` (to run `Check`s via `CheckStage`) and
`qai.engine.capture`/`qai.engine.modeler` (to implement `ReconStage`). Does **not**
import `qai.engine.runner` — avoids a cycle; `runner.py` imports `qai.engine.plugins`
for its own (parallel, non-pipeline) `PluginRunner` path.

## Pilot scope

Exactly two fixed stages: `recon` → `security_headers`. `run_scan`/`run_crawl` are NOT
refactored onto this abstraction in this plan — they stay parallel, unmodified code
paths. Crawl-wide driving (multi-page) is deferred to a follow-up plan.
