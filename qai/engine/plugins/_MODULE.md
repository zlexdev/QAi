# qai.engine.plugins

Check-plugin registry — pentest-style analysis families (security headers, auth-bypass,
IDOR, injection) attach as extra passes without touching the core fuzz oracle.

Full walkthrough with a worked example: [docs/PLUGINS.md](../../../docs/PLUGINS.md).

## Adding a check

1. Subclass `Check` (`contracts.py`) — set `name`, `kind` (`PASSIVE` or `ACTIVE`), optionally
   `timeout_s`, implement `async def run(self, ctx: CheckContext, replay=None) -> list[PluginFinding]`.
2. Decorate the class with `@register_check("your_name")` (`registry.py`).
3. Import the module from `checks/__init__.py` so registration runs as a side effect
   (same pattern as `qai/engine/fuzzer/strategies.py`).

## Isolation

Every check runs behind `run_with_containment` (`runner.py`) — a per-check
`asyncio.wait_for(..., timeout_s)` plus a catch-all `except Exception`. A slow or buggy
check can never stall or crash a scan; it just yields `CheckOutcome(status=TIMEOUT|ERROR)`
with zero findings.

## Consumption modes

One `Check` class, two callers:
- `PluginRunner` (this package) — invoked from `qai/engine/runner.py`'s `run_scan(plugins=[...])`.
- `CheckStage` (`qai/engine/pipeline/stages.py`) — invoked from the externally-driven pipeline.

Neither caller knows about the other. This package never imports `qai.engine.pipeline` or
`qai.engine.runner` — it's a leaf package, same shape as `qai/engine/fuzzer/`.

## Active checks + safe_mode gate

`idor` and `auth_bypass` (both `CheckKind.ACTIVE`) fire extra requests via
`replay.py`'s `ReplayClient` (wraps the SAME `CaptureSession` recon already opened —
no second browser). `PluginRunner`/`CheckStage` both gate any `ACTIVE` check on
`ctx.safe_mode: bool` (fail-safe default `True`, see `contracts.py`): when `True`, the
check is `SKIPPED` and `run()` is never called; `replay` is only constructed when a
real `ACTIVE` run happens. A check author never has to self-gate — write an `ACTIVE`
check exactly like a `PASSIVE` one.

Differential-response comparison shared by both active checks lives in
`checks/differential.py` (`similar_shape()`), not duplicated per-check.
