# pipeline/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

## contracts.py
```
# Pipeline contracts — the externally-driven, resumable state-machine seam (Design 2).

_FROZEN = ConfigDict(frozen=True, extra='forbid')

cls ReconStepConfig(BaseModel)

cls SecurityHeadersStepConfig(BaseModel)

cls StepStatus(StrEnum): PENDING, RUNNING, DONE, SKIPPED, ERROR

cls StepInfo(BaseModel)

cls PipelineState(BaseModel)

cls PentestContext: target_url: str, page: PageModel | None, effects: list[EffectBundle], core_findings: list[Finding], plugin_findings: list[PluginFinding], directives: list[AgentDirective], cookies: list[CookieSpec] | None, repo_path: str | None, safe_mode: bool

cls Stage(ABC)

```

## pipeline.py
```
# Pipeline — runs a fixed ordered list of Stages one at a time.


cls Pipeline
  __init__(session_id: str, stages: list[Stage, ctx: PentestContext) -> None
  ctx() -> PentestContext
  steps() -> list[StepInfo]
  cursor() -> int
  session_id() -> str
  bind_session_id(session_id: str) -> None
  restore(steps: list[StepInfo, cursor: int) -> None
    # Rehydrate step/cursor state loaded from SessionStore (restart-resume path).
  done() -> bool
  async step() -> list[PluginFinding]
  to_state() -> PipelineState

```

## session.py
```
# SessionStore — persists PentestContext/StepInfo/cursor to SQLite so a driven pipeline

IDLE_TTL_SECONDS = 600

cls SessionStore(ABC)
  async create(ctx: PentestContext, steps: list[StepInfo) -> str
  async load(session_id: str) -> tuple[PentestContext, list[StepInfo], int]
  async save(session_id: str, ctx: PentestContext, steps: list[StepInfo, cursor: int) -> None
  async delete(session_id: str) -> None

cls SqliteSessionStore(SessionStore)
  __init__(db_path: Path) -> None
  async create(ctx: PentestContext, steps: list[StepInfo) -> str
  async load(session_id: str) -> tuple[PentestContext, list[StepInfo], int]
  async save(session_id: str, ctx: PentestContext, steps: list[StepInfo, cursor: int) -> None
  async delete(session_id: str) -> None
  get_pool(session_id: str) -> BrowserPool | None
  set_pool(session_id: str, pool: BrowserPool) -> None
  evict_pool(session_id: str) -> BrowserPool | None
  async reap_idle_pools(ttl_seconds: float = IDLE_TTL_SECONDS) -> list[str]

_ctx_to_json(ctx: PentestContext) -> str

_ctx_from_json(raw: str) -> PentestContext

```

## stages.py
```
# Pipeline stages — ReconStage (fixed, first) and the generic CheckStage adapter.


cls ReconStage(Stage)
  __init__(session: CaptureSession) -> None

cls CheckStage(Stage)
  # Generic adapter — works for ANY registered Check, not just security_headers.
  __init__(check: Check, session: CaptureSession) -> None

```
