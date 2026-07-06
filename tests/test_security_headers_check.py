"""SecurityHeadersCheck — unit-level: constructs CapturedRequest/EffectBundle directly
(no browser needed), since the check only reads already-captured response headers."""

from __future__ import annotations

import pytest

from qai.engine.contracts import CapturedRequest, EffectBundle, HttpMethod, PageModel
from qai.engine.plugins.checks.security_headers import SecurityHeadersCheck
from qai.engine.plugins.contracts import CheckContext

pytestmark = pytest.mark.asyncio


def _effect(response_headers: dict[str, str] | None) -> EffectBundle:
    return EffectBundle(
        action_id="recon",
        requests=[
            CapturedRequest(
                method=HttpMethod.GET,
                url="https://example.test/",
                status=200,
                response_headers=response_headers,
            )
        ],
    )


async def test_missing_all_four_headers_yields_four_findings() -> None:
    ctx = CheckContext(page=PageModel(url="https://example.test/"), effects=[_effect({})])
    findings = await SecurityHeadersCheck().run(ctx)
    categories = {f.category for f in findings}
    assert categories == {
        "missing_csp",
        "missing_x_frame_options",
        "missing_hsts",
        "missing_x_content_type_options",
    }


async def test_all_headers_present_yields_no_findings() -> None:
    headers = {
        "Content-Security-Policy": "default-src 'self'",
        "X-Frame-Options": "DENY",
        "Strict-Transport-Security": "max-age=63072000",
        "X-Content-Type-Options": "nosniff",
    }
    ctx = CheckContext(page=PageModel(url="https://example.test/"), effects=[_effect(headers)])
    findings = await SecurityHeadersCheck().run(ctx)
    assert findings == []


async def test_request_with_no_captured_headers_is_skipped() -> None:
    ctx = CheckContext(page=PageModel(url="https://example.test/"), effects=[_effect(None)])
    findings = await SecurityHeadersCheck().run(ctx)
    assert findings == []
