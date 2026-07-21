from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from qai.engine.auth.contracts import LoginMacro
from qai.engine.contracts import CookieSpec


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class JobKind(StrEnum):
    SCAN = "scan"
    CRAWL = "crawl"
    API_SCAN = "api_scan"
    LOGIN_RECORD = "login_record"


class JobAccepted(BaseModel):
    job_id: str
    status: JobStatus


class JobStatusResponse(BaseModel):
    job_id: str
    kind: JobKind
    status: JobStatus
    result: dict[str, Any] | None = None
    error: str | None = None


# Request DTOs mirror the qa_* MCP tool params 1:1 (qai/mcp_server.py:147 qa_scan,
# :275 qa_crawl, :340 qa_api_scan, :380 qa_login_record) so the same call shape works
# over HTTP or MCP.


class ScanRequest(BaseModel):
    url: str
    repo_path: str | None = None
    headless: bool = True
    parallel: int = 1
    har_dir: str | None = None
    own_target: bool = False
    direct_mode: bool = False
    cookies: list[CookieSpec] | None = None
    plugins: list[str] | None = None
    login_macro: LoginMacro | None = None
    screenshot: bool = False
    screenshot_dir: str | None = None
    nav_timeout_seconds: float | None = None
    dom_stable_timeout_seconds: float | None = None


class CrawlRequest(BaseModel):
    url: str
    repo_path: str | None = None
    headless: bool = True
    max_depth: int = 2
    max_actions: int = 50
    wall_clock_seconds: int = 300
    include_subdomains: bool = True
    allowed_domains: list[str] | None = None
    screenshot: bool = False
    screenshot_dir: str | None = None
    # A list of selectors, not a bool — the same shape as qa_crawl's param and the CLI's
    # repeatable --allow-destructive. Permission is always per-control, never global.
    allow_destructive: list[str] | None = None
    parallel: int = 1
    own_target: bool = False
    direct_mode: bool = False
    cookies: list[CookieSpec] | None = None
    login_macro: LoginMacro | None = None
    nav_timeout_seconds: float | None = None
    dom_stable_timeout_seconds: float | None = None


class ApiScanRequest(BaseModel):
    spec: str
    base_url: str
    spec_kind: str = "openapi"
    repo_path: str | None = None
    headless: bool = True
    own_target: bool = False
    cookies: list[CookieSpec] | None = None
    login_macro: LoginMacro | None = None
    plugins: list[str] | None = None


class LoginRecordRequest(BaseModel):
    login_url: str
    username: str
    password: str
    success_indicator: str | None = None
    own_target: bool = False
    headless: bool = True


class PipelineStartRequest(BaseModel):
    url: str
    repo_path: str | None = None
    headless: bool = True
    own_target: bool = False
    cookies: list[CookieSpec] | None = None
    plugins: list[str] | None = None
    login_macro: LoginMacro | None = None


class PipelineStepRequest(BaseModel):
    inject: dict[str, Any] | None = None
    skip: bool = False
    config: dict[str, Any] | None = None
