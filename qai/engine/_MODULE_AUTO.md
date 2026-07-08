# engine/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

## Submodules

- [`apispec/`](apispec\_MODULE_AUTO.md) — apispec — OpenAPI/GraphQL spec parsing, converted to the existing FormModel/ (4 py, 4 cls, 14 fn)
- [`auth/`](auth\_MODULE_AUTO.md) — auth — one-time login recording (record_login) and deterministic replay (3 py, 2 cls, 6 fn)
- [`fuzzer/`](fuzzer\_MODULE_AUTO.md) (2 py, 10 cls, 2 fn)
- [`pipeline/`](pipeline\_MODULE_AUTO.md) (4 py, 12 cls, 2 fn)
- [`plugins/`](plugins\_MODULE_AUTO.md) (8 py, 11 cls, 9 fn)

## analyzer.py
```
# Analyzer — turns an EffectBundle + the fuzz intent into Findings (the error oracle).

_DETAIL_VALUE_PREVIEW = 80

cls Analyzer
  # Stateless: consumes one (plan, effect) pair, emits zero or more Findings.
  analyze(plan: FuzzPlan, effect: EffectBundle, submit_method: HttpMethod? = None, page_origin: str? = None) -> list[Finding]

_preview(value: str) -> str
  # Truncate a fuzz value for human-readable detail text (overflow cases are 100k chars).

```

## api_runner.py
```
# run_api_scan — spec-driven API scanning (OpenAPI/GraphQL). Parses the spec into


cls _ApiRequestExecutor
  __init__(session: CaptureSession, op: ApiOperation, base_url: str) -> None
  async run(plan: FuzzPlan) -> EffectBundle

_flatten_fields(operations: list[ApiOperation) -> list[FieldModel]

async run_api_scan(spec: ApiSpecSource, base_url: str, repo_path: str? = None, headless: bool = True, safe_mode: bool = True, cookies: list[CookieSpec]? = None, login_macro: LoginMacro? = None, plugins: list[str]? = None) -> RunReport

```

## capture.py
```
# CaptureSession — thin wrapper over Playwright + CDP that maps browser events to DTOs.

_NAV_TIMEOUT_MS = 15000
_SETTLE_MS = 800
_BODY_PREVIEW_LEN = 4000
_NETWORKIDLE_TIMEOUT_MS = 5000
_DOM_STABLE_TIMEOUT_MS = 4000
_DOM_STABLE_POLL_MS = 400
_DOM_STABLE_CONSECUTIVE = 2
_CF_WAIT_TIMEOUT_MS = 15000
_CF_POLL_MS = 500
_CF_TITLE_MARKERS = …
_ERROR_SELECTOR = …

cls BrowserPool: playwright: Playwright, browser: Browser

cls CaptureSession
  __init__() -> None
  page() -> Page
  async screenshot(path: str) -> bool
  tab_id() -> str
  request() -> APIRequestContext
  async open(url: str) -> None
  async cookies() -> list[CookieSpec]
  async capture(action_id: str, action: Callable[[], Awaitable[None) -> EffectBundle
    # Run ``action`` and return everything observed while it executed.

_origin_of(url: str) -> str

_truncate_body(body: str?) -> str | None

_method(raw: str) -> HttpMethod

_console_level(raw: str) -> ConsoleLevel

```

## contracts.py
```
# Frozen DTOs — the single vocabulary shared across every engine layer.

_FROZEN = ConfigDict(frozen=True, extra='forbid')

cls HttpMethod(StrEnum): GET, POST, PUT, PATCH, DELETE, HEAD, OPTIONS

cls ResponseKind(StrEnum): OK, CLIENT_ERROR, SERVER_ERROR, NETWORK_FAIL

cls ConsoleLevel(StrEnum): LOG, INFO, WARNING, ERROR

cls NavKind(StrEnum): REDIRECT, PUSH, RELOAD, NAVIGATE

cls FieldKind(StrEnum): TEXT, NUMBER, EMAIL, PASSWORD, DATE, SELECT, CHECKBOX, RADIO, FILE, TEXTAREA, UNKNOWN

cls FuzzIntent(StrEnum): VALID, EMPTY, BOUNDARY, OVERFLOW, MALICIOUS, UNICODE

cls ExpectedOutcome(StrEnum): ACCEPT, REJECT_GRACEFULLY, EITHER

cls Severity(StrEnum): HIGH, MEDIUM, LOW

cls FindingKind(StrEnum): SERVER_ERROR, CONSOLE_ERROR, NETWORK_FAIL, INVARIANT, BROKEN_LINK, DOM_ERROR

cls StackFrame(BaseModel)

cls ConsoleEntry(BaseModel)

cls NavEvent(BaseModel)

cls CapturedRequest(BaseModel)

cls EffectBundle(BaseModel)
  # Everything observed while executing one action (e.g. one form submission).

cls FieldConstraints(BaseModel)

cls FieldModel(BaseModel)

cls FormModel(BaseModel)
  # A submit-button and the fields that belong to it (DOM-grouped).

cls PageModel(BaseModel)

cls StateRef(BaseModel)

cls ActionKind(StrEnum): LINK, BUTTON, FORM_SUBMIT

cls CrawlAction(BaseModel)

cls FuzzCase(BaseModel)

cls SourceRef(BaseModel)
  # Where in the repository a request's handler is implemented.

cls Finding(BaseModel)

cls RequestTemplate(BaseModel)

cls SkipReason(StrEnum): BUDGET_MAX_ACTIONS, BUDGET_WALL_CLOCK, TRAP_DETECTED, REPLAY_FAILED, DUPLICATE_TEMPLATE

cls SkippedPage(BaseModel)
  # A page the crawler discovered a link/button to but never actually visited.

cls PluginFinding(BaseModel)

cls RunReport(BaseModel)
  # Top-level result of one scan — the machine output consumed by CLI/MCP/CI.
  ok() -> bool
  duration_seconds() -> float

cls CookieSpec(BaseModel)
  to_playwright() -> dict[str, str | bool]

cls CrawlBudget(BaseModel)

cls CrawlReport(BaseModel)
  # Aggregates every visited state's RunReport plus the discovered state graph.
  findings() -> list[Finding]
  plugin_findings() -> list[PluginFinding]
  ok() -> bool
  duration_seconds() -> float
  target_url() -> str
  forms_scanned() -> int
  cases_executed() -> int

```

## correlator.py
```
# CodeCorrelator — resolves a captured request to file:line in the target repo.

_ROUTE_METHODS = …
_PARAM_RE = re.compile('\\{[^{}]+\\}')

cls RouteEntry: method: HttpMethod, template: str, file: str, line: int, handler_symbol: str

cls RouteTable
  # route_template + method -> RouteEntry, built once per repo (incremental later).
  __init__(entries: list[RouteEntry) -> None
  resolve(method: HttpMethod, path: str) -> RouteEntry | None

cls CodeCorrelator
  # Resolves CapturedRequest -> SourceRef using the route table + optional cx.
  __init__(route_table: RouteTable, repo_path: Path) -> None
  correlate(request: CapturedRequest) -> SourceRef | None

build_route_table(repo_path: Path) -> RouteTable
  # Scan every ``*.py`` file under ``repo_path`` for FastAPI route decorators.

_scan_file(file: Path, repo_root: Path) -> list[RouteEntry]

_match_route_decorator(deco: ast.expr) -> tuple[HttpMethod, str] | None

_match(template: str, path: str) -> bool

_parse_cx_output(raw: str) -> tuple[list[str], list[str]]
  # Best-effort line-based parse of ``cx query --raw`` text output.

require_repo(repo_path: Path) -> Path

```

## direct_executor.py
```
# DirectExecutor — fast-path fuzzing that skips the DOM entirely.

_BODY_PREVIEW_LEN = 4000
_SIMPLE_CONTENT_TYPE = 'application/x-www-form-urlencoded'

cls DirectExecutor
  # Fires a FuzzPlan straight over HTTP using a learned RequestTemplate.
  __init__(session: CaptureSession, template: RequestTemplate) -> None
  async run(plan: FuzzPlan) -> EffectBundle

learn_template(form: FormModel, baseline_request: CapturedRequest) -> RequestTemplate | None
  # Build a RequestTemplate from the request produced by a baseline (all-valid) submit.

```

## errors.py
```
# Typed errors carrying arguments, never pre-formatted text. Never silenced upstream.


cls QaiError(Exception)
  # Base for every engine error.

cls InvalidTargetError(QaiError)
  # The URL or repo path failed boundary validation.
  __init__(value: str, reason: str) -> None

cls CaptureError(QaiError)
  # Browser/CDP navigation or capture failed after retries.
  __init__(url: str, cause: str) -> None

cls InvalidCookieSpecError(QaiError)
  # A ``--cookie``/MCP cookie argument didn't match ``domain:name=value``.
  __init__(raw: str, reason: str) -> None

cls RouteResolveError(QaiError)
  # A captured request could not be resolved to a source route.
  __init__(route: str?, cause: str) -> None

cls UnknownCheckError(QaiError)
  # A ``plugins=[...]`` entry doesn't match any registered check.
  __init__(name: str, available: list[str) -> None

cls UnknownSessionError(QaiError)
  # A pipeline session_id has no matching SQLite row (never existed, expired, or aborted).
  __init__(session_id: str) -> None

cls ReconNotRunError(QaiError)
  __init__(stage: str) -> None

cls InvalidStepConfigError(QaiError)
  # A ``config`` payload's ``stage`` discriminator doesn't match the pipeline's current stage.
  __init__(expected_stage: str, got_stage: str) -> None

cls InvalidSpecError(QaiError)
  # A ``--spec`` file failed to parse as OpenAPI or GraphQL.
  __init__(source: str, reason: str) -> None

cls LoginFailedError(QaiError)
  # record_login/replay_login's success_indicator never matched.
  __init__(login_url: str, reason: str) -> None

```

## executor.py
```
# FormExecutor — fills a form per a FuzzPlan and submits it, driving CaptureSession.

_TEXT_LIKE = …

cls FormExecutor
  # Fills every field in ``form`` with ``plan.values`` then submits it.
  __init__(session: CaptureSession) -> None
  async run(form: FormModel, plan: FuzzPlan) -> EffectBundle

```

## explorer.py
```
# Explorer — the state-graph crawler's outer loop.

_CLICK_SETTLE_MS = 500
_UNKNOWN_TARGET = '(unknown — SPA action chain, not a direct link)'
_FRONTIER_SAFETY_CAP = 2000

cls ExplorerResult: visited: list[tuple[StateRef, PageModel]], states: list[StateRef], skipped_destructive: list[CrawlAction], not_visited: list[SkippedPage], budget_exhausted_by: str | None

cls Explorer
  # Crawls same-origin states reachable from a root URL, within a CrawlBudget.
  __init__(session: CaptureSession, budget: CrawlBudget) -> None
  async crawl(root_url: str) -> ExplorerResult

_target_of(path: list[CrawlAction) -> str

```

## logging.py
```
# structlog configuration — run_id bound at entry, threaded through the whole crawl.


configure_logging() -> None
  # Idempotent structlog setup. Call once at process entry (CLI / MCP / tests).

get_logger(name: str) -> structlog.stdlib.BoundLogger

```

## modeler.py
```
# PageModeler — inventory of fields, types and form groups from a live page.

_SELECTOR_FOR_JS = …
_IS_VISIBLE_JS = …
_EXTRACT_JS = …
_DISCOVER_ACTIONS_JS = …

cls PageModeler
  # Extracts a typed :class:`PageModel` from a loaded Playwright page.
  async model(page: Page) -> PageModel
  async discover_actions(page: Page) -> list[dict[str, Any]]

_kind(raw: str?) -> FieldKind

_method(raw: str?) -> HttpMethod

_num(raw: Any) -> float | None

```

## reporter.py
```
# Reporter — the showcase surface. Terminal rich table + a self-contained dark HTML report.

_SEVERITY_STYLE = …
_SEVERITY_DOT = …
_SEVERITY_ORDER = …
_SEVERITY_COLOR = …

cls Reporter
  print_table(report: ScanReport, console: Console? = None) -> None
  write_json(report: ScanReport, path: Path) -> None
  write_html(report: ScanReport, path: Path) -> None
  write_markdown(report: ScanReport, path: Path) -> None
  write_findings(report: ScanReport, path: Path) -> None

_severity_key(finding: Finding) -> int

_render_html(report: ScanReport) -> str

_table_or_empty(report: ScanReport, rows: str) -> str

_plugin_section_html(report: ScanReport) -> str

_plugin_finding_row(f: PluginFinding) -> str

_render_markdown(report: ScanReport) -> str

_render_run_fields_markdown(report: RunReport) -> list[str]

_render_crawl_pages_markdown(report: CrawlReport) -> list[str]

_finding_row(f: Finding) -> str

```

## risk.py
```
# Destructive-action classifier — a heuristic, not a security guarantee.

_DESTRUCTIVE_KEYWORDS = …

is_destructive(label: str?) -> bool
  # True if ``label`` (button text / aria-label) matches a destructive keyword.

is_allowlisted(selector: str, allowlist: frozenset[str) -> bool

```

## runner.py
```
# Runner — the walking-skeleton pipeline: URL -> PageModel -> fuzz -> Findings -> RunReport.

_URL_RE = re.compile('^https?://', re.IGNORECASE)

validate_url(url: str) -> str

_flatten_fields(page_model: PageModel) -> list[FieldModel]

async _resolve_cookies(headless: bool, cookies: list[CookieSpec]?, login_macro: LoginMacro?) -> list[CookieSpec] | None

async run_scan(url: str, repo_path: str? = None) -> RunReport

async _recon(session: CaptureSession, url: str) -> tuple[PageModel, EffectBundle, str | None]

async _run_plugins(plugins: list[str]?, page_model: PageModel, recon_effect: EffectBundle, repo_path: str?, cookies: list[CookieSpec]?, session: CaptureSession, safe_mode: bool = True) -> list[PluginFinding]

async _fuzz_page_model() -> tuple[list[Finding], int, int, list[str]]

async _run_worker(url: str, bucket: list[WorkItem, tab_index: int, run_id: str, headless: bool, har_dir: str?, correlator: CodeCorrelator?, har_paths: list[str, direct_mode: bool, templates: dict[str, RequestTemplate?, pool: BrowserPool, stability_cache: dict[str, float, cookies: list[CookieSpec]? = None) -> list[Finding]

async _fuzz_form(session: CaptureSession, executor: FormExecutor, analyzer: Analyzer, templates: dict[str, RequestTemplate?, correlator: CodeCorrelator?, url: str, form: FormModel, plan: FuzzPlan, direct_mode: bool) -> list[Finding]

_learn_from_effect(form: FormModel, effect: EffectBundle) -> RequestTemplate | None

async run_crawl(url: str, repo_path: str? = None) -> CrawlReport

```

## state.py
```
# State identity for the crawler — a URL alone can't identify an SPA's in-memory

_ID_SEGMENT_RE = …
_STRUCTURAL_SIGNATURE_JS = …

normalize_url(url: str) -> str
  # Strip fragment (SPA router hash aside) and trailing slash for stable comparison.

url_template(url: str) -> str

async compute_state(page: Page, checkpoint_id: str = 'root') -> StateRef

```
