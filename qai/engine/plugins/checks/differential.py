"""Shared differential-response heuristic for the two active checks (IdorCheck,
AuthBypassCheck): "does a second request return a response shaped like the original
200?" Both checks compare on status + content-type + response body size — a heuristic
signal, not a certainty (see plan `05-risks.md` R-1/R-2)."""

from __future__ import annotations

from qai.engine.contracts import CapturedRequest


def _response_header(req: CapturedRequest, name: str) -> str | None:
    if req.response_headers is None:
        return None
    return req.response_headers.get(name)


def content_length(req: CapturedRequest) -> int | None:
    raw = _response_header(req, "content-length")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def similar_shape(original: CapturedRequest, candidate: CapturedRequest) -> bool:
    """True when ``candidate``'s response looks like a normal, successful response
    shaped like ``original``'s — same content-type, comparable body size.

    Compares via ``response_headers["content-type"]``, not the top-level
    ``content_type`` field — that field is populated from the REQUEST's own headers
    (a capture.py quirk, pre-existing), which is empty for a plain GET."""
    if candidate.status != 200:
        return False
    if _response_header(original, "content-type") != _response_header(candidate, "content-type"):
        return False
    orig_len = content_length(original)
    cand_len = content_length(candidate)
    if orig_len is None or cand_len is None:
        return True  # can't compare sizes — don't over-reject a heuristic signal
    if orig_len == 0:
        return cand_len == 0
    ratio = cand_len / orig_len
    return 0.5 <= ratio <= 2.0
