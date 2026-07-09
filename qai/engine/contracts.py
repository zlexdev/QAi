"""Frozen DTOs — the single vocabulary shared across every engine layer.

These types cross module boundaries (capture → analyze → correlate → report) and,
later, a REST/MCP boundary. Nothing here imports from other engine modules: contracts
are the leaf every layer depends on. No raw dict as a domain object anywhere downstream.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class HttpMethod(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class ResponseKind(StrEnum):
    OK = "ok"
    CLIENT_ERROR = "client_error"
    SERVER_ERROR = "server_error"
    NETWORK_FAIL = "network_fail"

    @classmethod
    def from_status(cls, status: int) -> ResponseKind:
        if status <= 0:
            return cls.NETWORK_FAIL
        if status >= 500:
            return cls.SERVER_ERROR
        if status >= 400:
            return cls.CLIENT_ERROR
        return cls.OK


class ConsoleLevel(StrEnum):
    LOG = "log"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class NavKind(StrEnum):
    REDIRECT = "redirect"
    PUSH = "push"
    RELOAD = "reload"
    NAVIGATE = "navigate"


class FieldKind(StrEnum):
    TEXT = "text"
    NUMBER = "number"
    EMAIL = "email"
    PASSWORD = "password"
    DATE = "date"
    SELECT = "select"
    CHECKBOX = "checkbox"
    RADIO = "radio"
    FILE = "file"
    TEXTAREA = "textarea"
    UNKNOWN = "unknown"


class FuzzIntent(StrEnum):
    VALID = "valid"
    EMPTY = "empty"
    BOUNDARY = "boundary"
    OVERFLOW = "overflow"
    MALICIOUS = "malicious"
    UNICODE = "unicode"


class ExpectedOutcome(StrEnum):
    ACCEPT = "accept"
    REJECT_GRACEFULLY = "reject_gracefully"
    EITHER = "either"


class Severity(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FindingKind(StrEnum):
    SERVER_ERROR = "server_error"
    CONSOLE_ERROR = "console_error"
    NETWORK_FAIL = "network_fail"
    INVARIANT = "invariant"
    BROKEN_LINK = "broken_link"
    DOM_ERROR = "dom_error"


class StackFrame(BaseModel):
    model_config = _FROZEN
    url: str
    function: str | None = None
    line: int | None = None
    column: int | None = None


class ConsoleEntry(BaseModel):
    model_config = _FROZEN
    level: ConsoleLevel
    text: str
    source_url: str | None = None
    line: int | None = None
    stack: list[StackFrame] = Field(default_factory=list)


class NavEvent(BaseModel):
    model_config = _FROZEN
    from_url: str
    to_url: str
    kind: NavKind
    status: int | None = None


class CapturedRequest(BaseModel):
    model_config = _FROZEN
    method: HttpMethod
    url: str
    route_template: str | None = None
    status: int = 0
    response_kind: ResponseKind = ResponseKind.NETWORK_FAIL
    initiator_stack: list[StackFrame] = Field(default_factory=list)
    request_body: str | None = None
    content_type: str | None = None
    started_at: datetime | None = None
    response_headers: dict[str, str] | None = None


class EffectBundle(BaseModel):
    """Everything observed while executing one action (e.g. one form submission)."""

    model_config = _FROZEN
    action_id: str
    tab_id: str = "tab-0"
    requests: list[CapturedRequest] = Field(default_factory=list)
    console: list[ConsoleEntry] = Field(default_factory=list)
    navigations: list[NavEvent] = Field(default_factory=list)
    page_error: str | None = None
    dom_errors: list[str] = Field(default_factory=list)


class FieldConstraints(BaseModel):
    model_config = _FROZEN
    required: bool = False
    min_length: int | None = None
    max_length: int | None = None
    minimum: float | None = None
    maximum: float | None = None
    pattern: str | None = None
    options: list[str] = Field(default_factory=list)


class FieldModel(BaseModel):
    model_config = _FROZEN
    selector: str
    name: str | None = None
    kind: FieldKind
    label: str | None = None
    group_id: str | None = None
    constraints: FieldConstraints = Field(default_factory=FieldConstraints)


class FormModel(BaseModel):
    """A submit-button and the fields that belong to it (DOM-grouped)."""

    model_config = _FROZEN
    group_id: str
    submit_selector: str | None
    action: str | None = None
    method: HttpMethod = HttpMethod.POST
    fields: list[FieldModel] = Field(default_factory=list)


class PageModel(BaseModel):
    model_config = _FROZEN
    url: str
    forms: list[FormModel] = Field(default_factory=list)


class StateRef(BaseModel):
    """A crawled state's identity — a URL alone isn't enough for SPAs, so identity
    also carries a structural DOM hash (tags/roles/hierarchy, never text/timestamps)."""

    model_config = _FROZEN
    normalized_url: str
    dom_hash: str
    checkpoint_id: str = "root"


class ActionKind(StrEnum):
    LINK = "link"
    BUTTON = "button"
    FORM_SUBMIT = "form_submit"


class CrawlAction(BaseModel):
    model_config = _FROZEN
    kind: ActionKind
    selector: str
    href: str | None = None  # LINK actions replay via direct navigation, not a click
    label: str | None = None
    destructive: bool = False


class FuzzCase(BaseModel):
    model_config = _FROZEN
    value: str
    intent: FuzzIntent
    expect: ExpectedOutcome


class SourceRef(BaseModel):
    """Where in the repository a request's handler is implemented."""

    model_config = _FROZEN
    file: str
    line: int
    symbol: str | None = None
    callees: list[str] = Field(default_factory=list)
    field_writes: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    model_config = _FROZEN
    severity: Severity
    kind: FindingKind
    action_id: str
    tab_id: str = "tab-0"
    detail: str
    field_selector: str | None = None
    intent: FuzzIntent | None = None
    request: CapturedRequest | None = None
    source_location: SourceRef | None = None
    console_ref: ConsoleEntry | None = None


class RequestTemplate(BaseModel):
    """Learned once per form from a baseline UI submission — enables the direct-request
    fast path (fuzz cases fire straight to the endpoint, no DOM/UI round-trip)."""

    model_config = _FROZEN
    method: HttpMethod
    url: str
    content_type: str
    body_template: str  # baseline body; a field's baseline value is substring-replaced
    field_values: dict[str, str]  # selector -> baseline value, must appear verbatim in body


class SkipReason(StrEnum):
    BUDGET_MAX_ACTIONS = "budget_max_actions"
    BUDGET_WALL_CLOCK = "budget_wall_clock"
    TRAP_DETECTED = "trap_detected"
    REPLAY_FAILED = "replay_failed"
    DUPLICATE_TEMPLATE = "duplicate_template"
    OFF_DOMAIN = "off_domain"


class BudgetExhaustedBy(StrEnum):
    MAX_ACTIONS = "max_actions"
    WALL_CLOCK = "wall_clock"


class SkippedPage(BaseModel):
    """A page the crawler discovered a link/button to but never actually visited."""

    model_config = _FROZEN
    url: str
    reason: SkipReason


class PluginFinding(BaseModel):
    """A finding from a check plugin — kept separate from Finding so the core FindingKind
    enum stays closed; plugin categories are free-form, not enum members."""

    model_config = _FROZEN
    plugin: str
    category: str
    severity: Severity
    title: str
    detail: str
    request: CapturedRequest | None = None
    source_location: SourceRef | None = None
    evidence: dict[str, str] = Field(default_factory=dict)


class RunReport(BaseModel):
    """Top-level result of one scan — the machine output consumed by CLI/MCP/CI."""

    model_config = _FROZEN
    run_id: str
    target_url: str
    repo_path: str | None = None
    started_at: datetime
    finished_at: datetime
    forms_scanned: int = 0
    cases_executed: int = 0
    tabs_used: int = 1
    har_paths: list[str] = Field(default_factory=list)
    safe_mode: bool = False
    fields_examined: list[FieldModel] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    plugin_findings: list[PluginFinding] = Field(default_factory=list)
    screenshot_path: str | None = None

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()


class CookieSpec(BaseModel):
    """One cookie to inject into the browser context before any navigation — lets a
    scan/crawl authenticate against a target (and, via ``domain``, against a separate
    SSO/auth subdomain the main site depends on) instead of only ever seeing the
    logged-out surface."""

    model_config = _FROZEN
    name: str
    value: str
    domain: str
    path: str = "/"
    # Most fuzz targets are staging/local http, not https — defaulting True would make
    # the cookie silently never leave the browser (secure cookies are https-only).
    secure: bool = False
    http_only: bool = False
    same_site: Literal["Strict", "Lax", "None"] = "Lax"

    def to_playwright(self) -> dict[str, str | bool]:
        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "secure": self.secure,
            "httpOnly": self.http_only,
            "sameSite": self.same_site,
        }


class TimeoutConfig(BaseModel):
    """Wait budgets for browser interactions. Override when a target is slow (heavy
    JS, distant/rate-limited hosting) instead of hardcoding a longer wait everywhere —
    a target that legitimately needs 30s to settle should not have to eat a
    ``replay_failed``/``CaptureError`` at the default 15s nav budget. Defaults match
    the values used before this was configurable."""

    model_config = _FROZEN
    nav_ms: int = 15_000
    networkidle_ms: int = 5_000
    dom_stable_ms: int = 4_000
    cloudflare_wait_ms: int = 15_000
    action_ms: int = 5_000
    fill_ms: int = 3_000


class CrawlBudget(BaseModel):
    model_config = _FROZEN
    max_depth: int = 2
    # Pages actually VISITED (root excluded), not links merely discovered — a nav menu
    # with 30 links must not exhaust this before the crawler leaves the root page.
    max_actions: int = 50
    wall_clock_seconds: int = 180
    trap_repeat_limit: int = 3
    # Caps how many URLs sharing the same path template (e.g. /lots/<id>) get queued —
    # the rest are recorded as SkipReason.DUPLICATE_TEMPLATE, never visited. Without this
    # a listing site with hundreds of same-shaped detail pages burns the whole budget
    # on near-identical pages before the crawler leaves the first template.
    max_pages_per_template: int = 1
    # Off-root-domain links (e.g. a Telegram/GitHub footer link from the target site)
    # are never followed — only the root's exact host, plus its subdomains when this
    # is True. Links outside scope are recorded as SkipReason.OFF_DOMAIN, never visited.
    include_subdomains: bool = True
    # Extra hosts allowed alongside the root's own (e.g. a separate auth/SSO or API
    # subdomain that isn't a subdomain of the root). Each entry follows the same
    # include_subdomains rule as the root host.
    allowed_domains: list[str] = Field(default_factory=list)


class CrawlReport(BaseModel):
    """Aggregates every visited state's RunReport plus the discovered state graph."""

    model_config = _FROZEN
    run_id: str
    root_url: str
    started_at: datetime
    finished_at: datetime
    states_visited: list[StateRef] = Field(default_factory=list)
    pages: list[RunReport] = Field(default_factory=list)
    pages_not_visited: list[SkippedPage] = Field(default_factory=list)
    pages_not_fuzzed: list[SkippedPage] = Field(default_factory=list)
    skipped_destructive: list[CrawlAction] = Field(default_factory=list)
    budget_exhausted_by: BudgetExhaustedBy | None = None

    @property
    def findings(self) -> list[Finding]:
        return [f for page in self.pages for f in page.findings]

    @property
    def plugin_findings(self) -> list[PluginFinding]:
        return [f for page in self.pages for f in page.plugin_findings]

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def duration_seconds(self) -> float:
        return (self.finished_at - self.started_at).total_seconds()

    # Aliases so Reporter (built for RunReport) renders a CrawlReport unchanged.
    @property
    def target_url(self) -> str:
        return self.root_url

    @property
    def forms_scanned(self) -> int:
        return sum(p.forms_scanned for p in self.pages)

    @property
    def cases_executed(self) -> int:
        return sum(p.cases_executed for p in self.pages)


# Reporter renders either shape — CrawlReport exposes the same read surface via aliases.
ScanReport = RunReport | CrawlReport
