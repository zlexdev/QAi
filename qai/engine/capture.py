"""CaptureSession — thin wrapper over Playwright + CDP that maps browser events to DTOs.

Primary signal is the backend response status (reliable); CDP ``initiator.stack`` is a
best-effort front-end enrichment (⚠️ unreliable on minified bundles without source maps —
see mini-plat §Gotchas), so a missing stack never fails a capture.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

from playwright.async_api import (
    APIRequestContext,
    Browser,
    BrowserContext,
    ConsoleMessage,
    Page,
    Playwright,
    Request,
    Response,
    async_playwright,
)

from qai.engine.contracts import (
    CapturedRequest,
    ConsoleEntry,
    ConsoleLevel,
    EffectBundle,
    HttpMethod,
    NavEvent,
    NavKind,
    ResponseKind,
    StackFrame,
)
from qai.engine.errors import CaptureError
from qai.engine.logging import get_logger

_log = get_logger("capture")

_NAV_TIMEOUT_MS = 15_000
_SETTLE_MS = 800
_BODY_PREVIEW_LEN = 4_000
_NETWORKIDLE_TIMEOUT_MS = 5_000
_DOM_STABLE_TIMEOUT_MS = 4_000
_DOM_STABLE_POLL_MS = 400
_DOM_STABLE_CONSECUTIVE = 2
_CF_WAIT_TIMEOUT_MS = 15_000
_CF_POLL_MS = 500
_CF_TITLE_MARKERS = ("just a moment", "checking your browser", "attention required")
_ERROR_SELECTOR = '[role="alert"], .error, .alert-danger, [aria-invalid="true"]'


@dataclass(slots=True)
class BrowserPool:
    """Shared Playwright + Browser process — N worker CaptureSessions borrow a
    BrowserContext each instead of each launching their own Chromium process.

    Caller owns the lifecycle: create once, pass to every CaptureSession that should
    share it, then ``await pool.close()`` after all sessions have exited.
    """

    playwright: Playwright
    browser: Browser

    @classmethod
    async def create(cls, *, headless: bool = True) -> BrowserPool:
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(headless=headless)
        return cls(playwright=pw, browser=browser)

    async def close(self) -> None:
        await self.browser.close()
        await self.playwright.stop()


def _origin_of(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _truncate_body(body: str | None) -> str | None:
    """Cap stored request bodies — overflow fuzz cases can be 100k+ chars, which would
    otherwise bloat every JSON report and log line with an unreadable wall of text."""
    if body is None or len(body) <= _BODY_PREVIEW_LEN:
        return body
    return f"{body[:_BODY_PREVIEW_LEN]}...(+{len(body) - _BODY_PREVIEW_LEN} chars truncated)"


class CaptureSession:
    """Owns one browser page and records effects of actions run against it.

    Use as an async context manager. ``capture()`` clears the per-action buffers,
    runs the supplied coroutine, lets the network settle, and returns an EffectBundle.
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        run_id: str = "-",
        tab_id: str = "tab-0",
        har_path: str | None = None,
        pool: BrowserPool | None = None,
        stability_cache: dict[str, float] | None = None,
    ) -> None:
        self._headless = headless
        self._run_id = run_id
        self._tab_id = tab_id
        self._har_path = har_path
        self._pool = pool
        # origin -> observed DOM-stability settle time (seconds); shared across tabs in
        # the same run so only the FIRST load of a given origin pays the full poll cap.
        self._stability_cache = stability_cache if stability_cache is not None else {}
        self._owns_browser = pool is None
        self._pw: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._requests: list[CapturedRequest] = []
        self._console: list[ConsoleEntry] = []
        self._navigations: list[NavEvent] = []
        self._page_error: str | None = None
        self._dom_errors: list[str] = []
        self._pre_action_errors: set[str] = set()
        # requestId -> initiator frames, filled from CDP before Playwright's response fires.
        self._initiators: dict[str, list[StackFrame]] = {}
        self._url_initiators: dict[str, list[StackFrame]] = {}

    @property
    def page(self) -> Page:
        if self._page is None:
            raise CaptureError(url="-", cause="session not opened")
        return self._page

    @property
    def tab_id(self) -> str:
        return self._tab_id

    @property
    def request(self) -> APIRequestContext:
        """The browser context's HTTP client — shares cookies/session with the page.
        Used by the direct-request fuzz fast path to fire fuzz cases without the DOM."""
        if self._context is None:
            raise CaptureError(url="-", cause="session not opened")
        return self._context.request

    async def __aenter__(self) -> Self:
        if self._pool is not None:
            self._browser = self._pool.browser
        else:
            self._pw = await async_playwright().start()
            self._browser = await self._pw.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context(record_har_path=self._har_path)
        self._page = await self._context.new_page()
        await self._wire_listeners(self._page)
        await self._wire_cdp(self._page)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        # A pooled browser/playwright is owned by the pool's creator — only ever close
        # the context this session made, never the shared process underneath it.
        if self._context is not None:
            await self._context.close()
        if self._owns_browser:
            if self._browser is not None:
                await self._browser.close()
            if self._pw is not None:
                await self._pw.stop()

    async def _wire_cdp(self, page: Page) -> None:
        try:
            cdp = await page.context.new_cdp_session(page)
            await cdp.send("Network.enable")
            cdp.on("Network.requestWillBeSent", self._on_cdp_request)
        except Exception as exc:
            _log.warning("cdp_unavailable", run_id=self._run_id, error=str(exc))

    def _on_cdp_request(self, params: dict[str, Any]) -> None:
        initiator = params.get("initiator") or {}
        frames_raw = (initiator.get("stack") or {}).get("callFrames") or []
        frames = [
            StackFrame(
                url=f.get("url", ""),
                function=f.get("functionName") or None,
                line=f.get("lineNumber"),
                column=f.get("columnNumber"),
            )
            for f in frames_raw
            if f.get("url")
        ]
        if not frames:
            return
        req_id = params.get("requestId")
        url = (params.get("request") or {}).get("url")
        if req_id:
            self._initiators[req_id] = frames
        if url:
            self._url_initiators[url] = frames

    async def _wire_listeners(self, page: Page) -> None:
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_request_failed)
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)
        page.on("framenavigated", self._on_frame_navigated)

    async def _on_response(self, response: Response) -> None:
        req = response.request
        if req.resource_type in {"image", "stylesheet", "font", "media"}:
            return
        self._requests.append(
            CapturedRequest(
                method=_method(req.method),
                url=req.url,
                status=response.status,
                response_kind=ResponseKind.from_status(response.status),
                initiator_stack=self._url_initiators.get(req.url, []),
                request_body=_truncate_body(req.post_data),
                content_type=req.headers.get("content-type"),
                started_at=datetime.now(UTC),
            )
        )

    async def _on_request_failed(self, request: Request) -> None:
        if request.resource_type in {"image", "stylesheet", "font", "media"}:
            return
        self._requests.append(
            CapturedRequest(
                method=_method(request.method),
                url=request.url,
                status=0,
                response_kind=ResponseKind.NETWORK_FAIL,
                initiator_stack=self._url_initiators.get(request.url, []),
                request_body=request.post_data,
                content_type=request.headers.get("content-type"),
                started_at=datetime.now(UTC),
            )
        )

    def _on_console(self, msg: ConsoleMessage) -> None:
        level = _console_level(msg.type)
        loc = msg.location or {}
        self._console.append(
            ConsoleEntry(
                level=level,
                text=msg.text,
                source_url=loc.get("url") or None,
                line=loc.get("lineNumber"),
            )
        )

    def _on_page_error(self, error: Any) -> None:
        text = getattr(error, "message", None) or str(error)
        self._page_error = text
        self._console.append(ConsoleEntry(level=ConsoleLevel.ERROR, text=text))

    def _on_frame_navigated(self, frame: Any) -> None:
        if frame.parent_frame is not None:
            return  # main frame only
        self._navigations.append(
            NavEvent(from_url="", to_url=frame.url, kind=NavKind.NAVIGATE)
        )

    def _reset(self) -> None:
        self._requests = []
        self._console = []
        self._navigations = []
        self._page_error = None
        self._dom_errors = []

    async def open(self, url: str) -> None:
        """Navigate to the target URL with a timeout and one retry, then let a
        Cloudflare JS challenge (if any) clear on its own before handing back control."""
        last: Exception | None = None
        for attempt in (1, 2):
            try:
                await self.page.goto(url, timeout=_NAV_TIMEOUT_MS, wait_until="domcontentloaded")
                await self._wait_out_cloudflare()
                await self._wait_networkidle_best_effort()
                self._reset()
                self._pre_action_errors = await self._snapshot_dom_errors()
                return
            except Exception as exc:
                last = exc
                _log.warning("open_retry", run_id=self._run_id, url=url, attempt=attempt)
                await asyncio.sleep(0.5)
        raise CaptureError(url=url, cause=str(last)) from last

    async def _wait_out_cloudflare(self) -> None:
        """Wait for an automatic Cloudflare JS challenge to clear. Never attempts to
        solve/click/bypass anything — an interactive CAPTCHA is left as-is and we
        simply proceed (the resulting capture will honestly show the challenge page)."""
        loop = asyncio.get_event_loop()
        deadline = loop.time() + _CF_WAIT_TIMEOUT_MS / 1000
        while loop.time() < deadline:
            title = (await self.page.title()).lower()
            if not any(marker in title for marker in _CF_TITLE_MARKERS):
                return
            await self.page.wait_for_timeout(_CF_POLL_MS)
        _log.warning("cloudflare_challenge_unresolved", run_id=self._run_id, tab_id=self._tab_id)

    async def _wait_networkidle_best_effort(self) -> None:
        """SPAs with long-polling/websockets never reach networkidle — cap it low and
        treat a timeout as normal, not an error."""
        # Best-effort stability wait — a timeout here is normal (SPAs keep polling), not an error.
        with contextlib.suppress(Exception):
            await self.page.wait_for_load_state("networkidle", timeout=_NETWORKIDLE_TIMEOUT_MS)
        await self._wait_dom_stable()

    async def _wait_dom_stable(self) -> None:
        """Hydration-aware settle: frameworks like Next.js reach ``networkidle`` before
        client components finish mounting, so interactive elements (buttons, forms) can
        still be absent right after navigation. Poll the element count until it stops
        growing, capped low so static pages don't pay the cost.

        The poll budget for an origin shrinks after its first observed settle time
        (cached, shared across tabs in the same run via ``self._stability_cache``) — a
        static/SSR page (qai's primary FastAPI target) stops paying the full worst-case
        cap on every one of its many reloads between fuzz cases. The cache only ever
        grows to the *max* observed settle time for that origin, never below it, so a
        one-off slow load doesn't get under-budgeted on a later reload.
        """
        origin = _origin_of(self.page.url)
        cached_ms = self._stability_cache.get(origin)
        floor_ms = _DOM_STABLE_POLL_MS * (_DOM_STABLE_CONSECUTIVE + 1)
        budget_ms = (
            _DOM_STABLE_TIMEOUT_MS
            if cached_ms is None
            else min(_DOM_STABLE_TIMEOUT_MS, max(cached_ms * 1.5, floor_ms))
        )

        loop = asyncio.get_event_loop()
        start = loop.time()
        deadline = start + budget_ms / 1000
        try:
            last_count = await self.page.evaluate("document.querySelectorAll('*').length")
        except Exception:
            return
        consecutive_matches = 0
        while loop.time() < deadline and consecutive_matches < _DOM_STABLE_CONSECUTIVE:
            await self.page.wait_for_timeout(_DOM_STABLE_POLL_MS)
            try:
                count = await self.page.evaluate("document.querySelectorAll('*').length")
            except Exception:
                return
            consecutive_matches = consecutive_matches + 1 if count == last_count else 0
            last_count = count

        elapsed_ms = (loop.time() - start) * 1000
        self._stability_cache[origin] = max(cached_ms or 0.0, elapsed_ms)

    async def _snapshot_dom_errors(self) -> set[str]:
        try:
            texts: list[str] = await self.page.eval_on_selector_all(
                _ERROR_SELECTOR, "els => els.map(e => e.innerText.trim()).filter(Boolean)"
            )
            return set(texts)
        except Exception:
            return set()

    async def capture(
        self, action_id: str, action: Callable[[], Awaitable[None]]
    ) -> EffectBundle:
        """Run ``action`` and return everything observed while it executed."""
        self._reset()
        try:
            await action()
        except Exception as exc:
            _log.warning("action_error", run_id=self._run_id, action_id=action_id, error=str(exc))
        await self.page.wait_for_timeout(_SETTLE_MS)
        post_errors = await self._snapshot_dom_errors()
        new_errors = sorted(post_errors - self._pre_action_errors)
        return EffectBundle(
            action_id=action_id,
            tab_id=self._tab_id,
            requests=list(self._requests),
            console=list(self._console),
            navigations=list(self._navigations),
            page_error=self._page_error,
            dom_errors=new_errors,
        )


def _method(raw: str) -> HttpMethod:
    try:
        return HttpMethod(raw.upper())
    except ValueError:
        return HttpMethod.GET


def _console_level(raw: str) -> ConsoleLevel:
    mapping = {
        "error": ConsoleLevel.ERROR,
        "warning": ConsoleLevel.WARNING,
        "warn": ConsoleLevel.WARNING,
        "info": ConsoleLevel.INFO,
    }
    return mapping.get(raw, ConsoleLevel.LOG)
