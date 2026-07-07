"""ReplayClient — the active-check I/O seam: fires an extra HTTP request outside the
normal capture flow, bound to the SAME CaptureSession's request context (no second
browser/session spin-up). Concrete class, not an ABC — only one transport is named or
probable (Decision A, plan `00-decisions.md` D1)."""

from __future__ import annotations

from datetime import UTC, datetime

from qai.engine.capture import CaptureSession
from qai.engine.contracts import CapturedRequest, HttpMethod, ResponseKind


class ReplayClient:
    """Fires an extra HTTP request outside the normal capture flow, for ACTIVE checks.
    Wraps the SAME CaptureSession's request context — no second session."""

    def __init__(self, session: CaptureSession) -> None:
        self._session = session

    async def fire(
        self,
        method: HttpMethod,
        url: str,
        *,
        body: str | None = None,
        headers: dict[str, str] | None = None,
        strip_auth: bool = False,
    ) -> CapturedRequest:
        """``strip_auth=True`` sends the request with no Cookie/Authorization header,
        regardless of the session's live cookie jar — used by AuthBypassCheck. Never
        mutates the session's own cookie jar (R-3): Playwright's ``APIRequestContext``
        shares the browser context's cookies by default, so stripping is done by
        overriding this one call's headers, not by touching the context's jar."""
        fire_headers = dict(headers or {})
        if strip_auth:
            fire_headers["Cookie"] = ""
            fire_headers.pop("Authorization", None)
            fire_headers.pop("authorization", None)

        response = await self._session.request.fetch(
            url,
            method=method.value,
            headers=fire_headers or None,
            data=body,
        )
        response_headers = dict(response.headers)
        return CapturedRequest(
            method=method,
            url=url,
            status=response.status,
            response_kind=ResponseKind.from_status(response.status),
            request_body=body,
            content_type=response_headers.get("content-type"),
            started_at=datetime.now(UTC),
            response_headers=response_headers,
        )
