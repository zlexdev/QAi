# Writing a check plugin

qai's fuzz oracle (5xx / console-error under fuzzing) covers one class of bug. A **check
plugin** attaches a second, independent analysis pass — security headers, auth-bypass,
IDOR, injection-pattern detection — without touching the core fuzz engine. One `Check`
class you write runs in two places for free: as a background pass inside `qa_scan`, and
as a steerable stage in the externally-driven MCP pipeline (`qa_pipeline_start/step`).

Package: `qai/engine/plugins/`. See also `qai/engine/plugins/_MODULE.md` for the terse
in-repo version of this guide.

## The contract

```python
class Check(ABC):
    name: str                      # set by @register_check, not by you
    kind: CheckKind                 # PASSIVE or ACTIVE
    timeout_s: float = 10.0         # your own budget — a slow check gets cut off, not the scan

    @abstractmethod
    async def run(self, ctx: CheckContext, replay: object | None = None) -> list[PluginFinding]:
        ...
```

- **`PASSIVE`** — reads what was already captured (`ctx.effects: list[EffectBundle]`,
  each carrying `requests: list[CapturedRequest]` with `response_headers`). No extra
  network calls. This is the only kind the pilot ships (`security_headers`).
- **`ACTIVE`** — issues its own extra requests (e.g. an IDOR replay with a mutated id).
  Needs a `replay` handle — not built yet; deferred until the first active check lands
  (it will need `safe_mode`/`own_target` gating, same as destructive crawl actions).

`CheckContext` is a frozen DTO: the page model, captured effects, cookies, `repo_path`,
and any `AgentDirective`s an external agent injected between pipeline steps (`notes`,
`focus_selectors`, `focus_params`, `hints` — read these if your check can narrow its
work based on operator/agent hints, otherwise ignore them).

## Step by step

**1. Write the check**, in its own file under `qai/engine/plugins/checks/`:

```python
# qai/engine/plugins/checks/security_headers.py
from qai.engine.contracts import PluginFinding, Severity
from qai.engine.plugins.contracts import Check, CheckContext, CheckKind
from qai.engine.plugins.registry import register_check

_REQUIRED_HEADERS = {
    "content-security-policy": "missing_csp",
    "x-frame-options": "missing_x_frame_options",
    "strict-transport-security": "missing_hsts",
    "x-content-type-options": "missing_x_content_type_options",
}


@register_check("security_headers")
class SecurityHeadersCheck(Check):
    kind = CheckKind.PASSIVE
    timeout_s = 5.0

    async def run(self, ctx: CheckContext, replay: object | None = None) -> list[PluginFinding]:
        findings: list[PluginFinding] = []
        seen_urls: set[str] = set()
        for effect in ctx.effects:
            for req in effect.requests:
                if req.url in seen_urls or req.response_headers is None:
                    continue
                seen_urls.add(req.url)
                headers_lower = {k.lower(): v for k, v in req.response_headers.items()}
                for header, category in _REQUIRED_HEADERS.items():
                    if header not in headers_lower:
                        findings.append(
                            PluginFinding(
                                plugin=self.name,
                                category=category,
                                severity=Severity.LOW,
                                title=f"Missing {header} response header",
                                detail=f"{req.url} responded without a {header!r} header.",
                                request=req,
                            )
                        )
        return findings
```

Notes on the shape:
- `@register_check("your_name")` sets `cls.name` and stores the **class** (not an
  instance) in the registry — `iter_checks()` instantiates fresh per call, so two
  concurrent scans/pipeline sessions never share one check's mutable state.
- `PluginFinding.category` is a free-form `str`, not a closed enum — each plugin owns
  its own category vocabulary; the core `FindingKind` enum never grows per plugin.
- Return `[]` if nothing's wrong. Never raise for an expected "no finding" case — only
  raise for a genuine check failure (network error, malformed input), and even then
  `run_with_containment` (below) catches it for you.

**2. Register the import** in `qai/engine/plugins/checks/__init__.py` so the
`@register_check` decorator runs as a side effect on package import:

```python
from qai.engine.plugins.checks import security_headers as security_headers

__all__ = ["security_headers"]
```

A check that isn't imported from here never registers — `iter_checks(["your_name"])`
will raise `UnknownCheckError` listing what's actually available.

**3. Write a test** (`tests/test_<name>_check.py`) against a real fixture, not mocks —
see `tests/test_security_headers_check.py`: spin a minimal FastAPI/uvicorn app, run
`run_scan(url, plugins=["your_name"])`, assert on `report.plugin_findings`.

That's it — no wiring in `runner.py`, `mcp_server.py`, or the pipeline is needed. The
registry + two generic consumers (below) pick up any registered check automatically.

## Isolation — you don't write this part

Every check runs behind `run_with_containment` (`qai/engine/plugins/runner.py`):

```python
async def run_with_containment(
    coro: Awaitable[T], timeout_s: float
) -> tuple[T | None, CheckStatus, str | None]: ...
```

A per-check `asyncio.wait_for(check.run(...), check.timeout_s)` plus a catch-all
`except Exception`. If your check hangs or throws, it yields
`CheckOutcome(status=TIMEOUT|ERROR)` with zero findings — it can never stall or crash
the scan or the driven pipeline. Set `timeout_s` to whatever your check's own I/O
budget should be; the default (10s) is generous for a passive header/pattern check.

This same primitive is shared by `PluginRunner` (below) and `CheckStage` — written
once, so both consumption modes get the same isolation guarantee for free.

## Two consumption modes, one class

You write ONE `Check` subclass. It runs in both places without any extra code:

**Mode A — background pass inside `qa_scan`** (`qai/engine/runner.py`):
```python
report = await run_scan(url, repo_path, plugins=["security_headers"])
# report.plugin_findings: list[PluginFinding]
```
`PluginRunner(iter_checks(plugins)).run(ctx)` fans every requested check out via
`asyncio.gather` (safe without `return_exceptions=True` — `run_with_containment`
already guarantees no check ever raises past its own boundary).

**Mode B — a stage in the externally-driven MCP pipeline** (`qai/engine/pipeline/`):
```python
await qa_pipeline_start(url, plugins=["security_headers"])   # stages: [recon, security_headers]
await qa_pipeline_step(session_id)                            # runs recon
await qa_pipeline_step(session_id, inject={"notes": "..."})   # runs your check, one step at a time
```
`CheckStage(check=SecurityHeadersCheck())` wraps any `Check` instance as a `Stage` —
an external agent (Claude Code, or any MCP client) can inspect each step's output,
inject an `AgentDirective`, or skip your check entirely before deciding to run it.

Neither mode's code needs to know your check exists in advance — both resolve checks
by name through the same registry.

## Active checks (not yet built)

`CheckKind.ACTIVE` and the `replay` parameter are reserved for checks that fire their
own extra requests (IDOR replay with a mutated id, auth-bypass re-fire without
cookies). Building one will need:
- A `ReplayClient` type (the `replay: object | None` parameter is a placeholder for
  this — it will become `ReplayClient | None` once the first active check lands).
- Gating behind `safe_mode`/`own_target`, the same rule that already protects
  destructive crawl actions — an active check is an attacker and must not fire against
  a target the caller doesn't own.

This is scoped out of the current pilot (see `.plans/pentest-plugins-and-driven-pipeline/00-decisions.md`)
deliberately — don't build it speculatively; wait until a concrete active check needs it.

## Layering rule

`qai/engine/plugins/` is a leaf package: it imports only from `qai.engine.contracts`,
never from `qai.engine.pipeline` or `qai.engine.runner`. `pipeline/` imports `plugins/`
(via `CheckStage`), never the reverse. Keep new checks inside this rule — a check module
that needs something from `pipeline/` is a sign the check belongs in `pipeline/stages.py`
instead, or that the contract it needs should move down into `qai.engine.contracts`.
