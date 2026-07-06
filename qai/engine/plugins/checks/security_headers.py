"""First passive check — inspects already-captured response headers for a missing
security-relevant set. Static per-origin, so the recon page-load response is sufficient
(doesn't need to vary per fuzz payload)."""

from __future__ import annotations

from qai.engine.contracts import PluginFinding, Severity
from qai.engine.plugins.contracts import Check, CheckContext, CheckKind
from qai.engine.plugins.registry import register_check

_REQUIRED_HEADERS = {
    "content-security-policy": "missing_csp",
    "x-frame-options": "missing_x_frame_options",
    "strict-transport-security": "missing_hsts",
    "x-content-type-options": "missing_x_content_type_options",
}


@register_check("security_headers")
class SecurityHeadersCheck(Check):
    kind = CheckKind.PASSIVE
    timeout_s = 5.0

    async def run(self, ctx: CheckContext, replay: object | None = None) -> list[PluginFinding]:
        findings: list[PluginFinding] = []
        seen_urls: set[str] = set()
        for effect in ctx.effects:
            for req in effect.requests:
                if req.url in seen_urls or req.response_headers is None:
                    continue
                seen_urls.add(req.url)
                headers_lower = {k.lower(): v for k, v in req.response_headers.items()}
                for header, category in _REQUIRED_HEADERS.items():
                    if header not in headers_lower:
                        findings.append(
                            PluginFinding(
                                plugin=self.name,
                                category=category,
                                severity=Severity.LOW,
                                title=f"Missing {header} response header",
                                detail=f"{req.url} responded without a {header!r} header.",
                                request=req,
                            )
                        )
        return findings
