"""Frozen DTOs — the single vocabulary shared across every engine layer.

These types cross module boundaries (capture → analyze → correlate → report) and,
later, a REST/MCP boundary. Nothing here imports from other engine modules: contracts
are the leaf every layer depends on. No raw dict as a domain object anywhere downstream.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

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
    findings: list[Finding] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings
