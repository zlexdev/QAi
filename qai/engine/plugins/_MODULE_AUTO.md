# plugins/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

## Submodules

- [`checks/`](checks\_MODULE_AUTO.md) — Importing this subpackage registers every built-in check as a side effect — same (4 py, 3 cls, 6 fn)

## contracts.py
```
# Check-plugin contracts — the seam a pentest-style check family attaches through.

_FROZEN = ConfigDict(frozen=True, extra='forbid')

cls CheckKind(StrEnum): PASSIVE, ACTIVE

cls CheckStatus(StrEnum): OK, TIMEOUT, ERROR, SKIPPED

cls AgentDirective(BaseModel)

cls CheckContext(BaseModel)

cls CheckOutcome(BaseModel)

cls Check(ABC)
  async run(ctx: CheckContext, replay: ReplayClient? = None) -> list[PluginFinding]

```

## registry.py
```
# Check registry — same decorator+dict+lookup shape as ``fuzzer/strategies.py``, but


register_check(name: str) -> Callable[[type[Check]], type[Check]]

iter_checks(names: list[str) -> list[Check]

```

## replay.py
```
# ReplayClient — the active-check I/O seam: fires an extra HTTP request outside the


cls ReplayClient
  __init__(session: CaptureSession) -> None
  async fire(method: HttpMethod, url: str) -> CapturedRequest

```

## runner.py
```
# Isolation primitive + PluginRunner — bounded fan-out over registered checks.


cls PluginRunner
  __init__(checks: list[Check, session: CaptureSession) -> None
  async run(ctx: CheckContext) -> list[CheckOutcome]

async run_with_containment(coro: Awaitable[T, timeout_s: float) -> tuple[T | None, CheckStatus, str | None]
  # Returns ``(result_or_None, status, error_message_or_None)`` — never raises.

```
