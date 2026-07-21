# api/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

## app.py
```
create_app() -> FastAPI

main() -> None

```

## auth.py
```
get_settings() -> Settings

async require_api_key(presented: str? = ..., settings: Settings = ...) -> None

```

## errors.py
```
cls JobNotFoundError(Exception)
  __init__(job_id: str) -> None

cls InvalidApiKeyError(Exception)
  # ``X-API-Key`` header missing or not equal to ``Settings.api_key``.

```

## jobs.py
```
cls Job: job_id: str, kind: JobKind, status: JobStatus, result: dict[str, Any] | None, error: str | None

cls JobStore: _jobs: dict[str, Job], _lock: asyncio.Lock, _background_tasks: set[asyncio.Task[None]]

```

## pipeline_runtime.py
```
DEFAULT_PIPELINE_PLUGINS = ['security_headers']

cls PipelineRuntime
  __init__(db_path: Path) -> None
  async start(url: str) -> PipelineState
  async step(session_id: str) -> PipelineState
  async report(session_id: str) -> RunReport
  async abort(session_id: str) -> None

_build_stages(session: CaptureSession, plugin_names: list[str) -> list[Stage]

_plugin_names_from_steps(steps: list[StepInfo) -> list[str]

```

## routes.py
```
_LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}

get_pipeline_runtime() -> PipelineRuntime

_resolve_safe_mode(url: str, own_target: bool) -> bool

_build_timeouts(nav_timeout_seconds: float?, dom_stable_timeout_seconds: float?) -> TimeoutConfig | None

async healthz() -> dict[str, str]

async submit_scan(req: ScanRequest) -> JobAccepted

async submit_crawl(req: CrawlRequest) -> JobAccepted

async submit_api_scan(req: ApiScanRequest) -> JobAccepted

async submit_login_record(req: LoginRecordRequest) -> JobAccepted

async get_job(job_id: str) -> JobStatusResponse

async pipeline_start(req: PipelineStartRequest, runtime: PipelineRuntime = ...) -> PipelineState

async pipeline_step(session_id: str, req: PipelineStepRequest, runtime: PipelineRuntime = ...) -> PipelineState

async pipeline_report(session_id: str, runtime: PipelineRuntime = ...) -> dict[str, Any]

async pipeline_abort(session_id: str, runtime: PipelineRuntime = ...) -> dict[str, bool]

```

## schemas.py
```
cls JobStatus(StrEnum): PENDING, RUNNING, DONE, ERROR

cls JobKind(StrEnum): SCAN, CRAWL, API_SCAN, LOGIN_RECORD

cls JobAccepted(BaseModel)

cls JobStatusResponse(BaseModel)

cls ScanRequest(BaseModel)

cls CrawlRequest(BaseModel)

cls ApiScanRequest(BaseModel)

cls LoginRecordRequest(BaseModel)

cls PipelineStartRequest(BaseModel)

cls PipelineStepRequest(BaseModel)

```

## settings.py
```
cls Settings(BaseSettings)

```
