"""IdorCheck — active check: adjacent-id replay + differential response. Flags an
endpoint that returns a DIFFERENT resource to the SAME authenticated session merely by
changing a numeric id in the URL path (candidate IDOR — Insecure Direct Object
Reference).

Heuristic, not a proof (05-risks.md R-1): MEDIUM severity, findings are worded as a
candidate to verify manually. UUID-templated paths are skipped in v1 — no meaningful
arithmetic mutation exists for them (documented limitation)."""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from qai.engine.contracts import CapturedRequest, PluginFinding, Severity
from qai.engine.plugins.checks.differential import similar_shape
from qai.engine.plugins.contracts import Check, CheckContext, CheckKind
from qai.engine.plugins.registry import register_check
from qai.engine.plugins.replay import ReplayClient
from qai.engine.state import url_template

_NUMERIC_SEGMENT = str.isdigit


def _path_segments(url: str) -> list[str]:
    return [s for s in urlsplit(url).path.split("/") if s]


def _numeric_id_index(segments: list[str]) -> int | None:
    for i, seg in enumerate(segments):
        if _NUMERIC_SEGMENT(seg):
            return i
    return None


def _with_segment(url: str, index: int, new_value: str) -> str:
    parts = urlsplit(url)
    segments = _path_segments(url)
    segments[index] = new_value
    return urlunsplit((parts.scheme, parts.netloc, "/" + "/".join(segments), parts.query, ""))


@register_check("idor")
class IdorCheck(Check):
    kind = CheckKind.ACTIVE
    timeout_s = 15.0

    async def run(
        self, ctx: CheckContext, replay: ReplayClient | None = None
    ) -> list[PluginFinding]:
        if replay is None:
            return []
        findings: list[PluginFinding] = []
        ok_requests = [
            req for effect in ctx.effects for req in effect.requests if req.status == 200
        ]

        grouped: dict[str, list[CapturedRequest]] = {}
        for req in ok_requests:
            grouped.setdefault(url_template(req.url), []).append(req)

        for template, reqs in grouped.items():
            if "#" not in template:
                continue
            findings.extend(await self._check_template(replay, reqs))
        return findings

    async def _check_template(
        self, replay: ReplayClient, reqs: list[CapturedRequest]
    ) -> list[PluginFinding]:
        representative = reqs[0]
        segments = _path_segments(representative.url)
        idx = _numeric_id_index(segments)
        if idx is None:
            return []  # UUID-templated or non-numeric id — v1 skip (documented limitation)

        original_id_str = segments[idx]
        observed_ids: set[str] = set()
        for r in reqs:
            r_segments = _path_segments(r.url)
            if idx < len(r_segments):
                observed_ids.add(r_segments[idx])
        try:
            original_id = int(original_id_str)
        except ValueError:
            return []

        candidates = {str(original_id - 1), str(original_id + 1)}
        candidates |= observed_ids
        candidates.discard(original_id_str)
        candidates = {c for c in candidates if c.isdigit() and int(c) >= 0}

        findings: list[PluginFinding] = []
        for candidate in candidates:
            mutated_url = _with_segment(representative.url, idx, candidate)
            mutated = await replay.fire(representative.method, mutated_url)
            if similar_shape(representative, mutated) and candidate not in observed_ids:
                findings.append(
                    PluginFinding(
                        plugin=self.name,
                        category="idor_candidate",
                        severity=Severity.MEDIUM,
                        title=f"Possible IDOR at {representative.url}",
                        detail=(
                            f"candidate — verify manually: replacing id {original_id_str!r} with "
                            f"{candidate!r} returned {mutated.status} with a similarly-shaped body "
                            "under the SAME session/cookies."
                        ),
                        request=mutated,
                        evidence={"original_id": original_id_str, "candidate_id": candidate},
                    )
                )
        return findings
