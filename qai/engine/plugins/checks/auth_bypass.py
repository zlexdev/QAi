"""AuthBypassCheck — active check: re-fires a captured request with auth stripped
(no Cookie/Authorization header) and flags an endpoint whose response doesn't change —
i.e. it isn't actually enforcing the authentication the caller assumed it required.

A 401/403/redirect on the stripped call is the expected/healthy outcome and produces no
finding. Heuristic (05-risks.md R-2): an intentionally-public endpoint (health check,
public listing) can false-positive — HIGH severity is still warranted as "worth a human
look", worded as a differential observation, not a confirmed vulnerability."""

from __future__ import annotations

from qai.engine.contracts import PluginFinding, Severity
from qai.engine.plugins.checks.differential import similar_shape
from qai.engine.plugins.contracts import Check, CheckContext, CheckKind
from qai.engine.plugins.registry import register_check
from qai.engine.plugins.replay import ReplayClient


@register_check("auth_bypass")
class AuthBypassCheck(Check):
    kind = CheckKind.ACTIVE
    timeout_s = 15.0

    async def run(self, ctx: CheckContext, replay: ReplayClient | None) -> list[PluginFinding]:
        if replay is None or not ctx.cookies:
            return []  # nothing was authenticated in this session — nothing to bypass

        findings: list[PluginFinding] = []
        seen_urls: set[str] = set()
        for effect in ctx.effects:
            for req in effect.requests:
                if req.status != 200 or req.url in seen_urls:
                    continue
                seen_urls.add(req.url)

                stripped = await replay.fire(
                    req.method, req.url, body=req.request_body, strip_auth=True
                )
                if similar_shape(req, stripped):
                    findings.append(
                        PluginFinding(
                            plugin=self.name,
                            category="auth_bypass",
                            severity=Severity.HIGH,
                            title=f"Possible auth bypass at {req.url}",
                            detail=(
                                f"differential observation — verify manually: {req.url!r} "
                                f"returned {stripped.status} with a similarly-shaped body even "
                                "with Cookie/Authorization stripped from the request."
                            ),
                            request=stripped,
                        )
                    )
        return findings
