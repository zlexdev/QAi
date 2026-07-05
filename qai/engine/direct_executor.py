"""DirectExecutor — fast-path fuzzing that skips the DOM entirely.

Learns a form's request shape from ONE baseline (valid) UI submission, then fires every
remaining fuzz case straight over HTTP via the same browser context's ``APIRequestContext``
(shares cookies/session with the page). No selector to fill, no client-side maxlength/
type=number fighting the payload — matches the analyzer oracle's actual target, the
*server's* validation.

Only activates for a simple ``application/x-www-form-urlencoded`` body where every field's
baseline value is traceable 1:1 to a form input (unique, non-empty). Anything else
(multipart, JSON with client-computed fields, duplicate values) yields ``None`` and the
caller keeps using the UI-driven :class:`~qai.engine.executor.FormExecutor` for that form —
we never guess at a payload shape we can't reconstruct faithfully.
"""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode

from qai.engine.capture import CaptureSession
from qai.engine.contracts import (
    CapturedRequest,
    EffectBundle,
    FormModel,
    RequestTemplate,
    ResponseKind,
)
from qai.engine.fuzzer.generator import FuzzPlan
from qai.engine.logging import get_logger

_log = get_logger("direct_executor")
_BODY_PREVIEW_LEN = 4_000
_SIMPLE_CONTENT_TYPE = "application/x-www-form-urlencoded"


def learn_template(form: FormModel, baseline_request: CapturedRequest) -> RequestTemplate | None:
    """Build a RequestTemplate from the request produced by a baseline (all-valid) submit."""
    content_type = baseline_request.content_type or ""
    if baseline_request.request_body is None or _SIMPLE_CONTENT_TYPE not in content_type:
        _log.info("direct_mode_unavailable", group_id=form.group_id, content_type=content_type)
        return None

    pairs = parse_qsl(baseline_request.request_body, keep_blank_values=True)
    by_name = dict(pairs)
    value_counts: dict[str, int] = {}
    for _, value in pairs:
        value_counts[value] = value_counts.get(value, 0) + 1

    field_values: dict[str, str] = {}
    for field in form.fields:
        if field.name is None or field.name not in by_name:
            return None
        value = by_name[field.name]
        # An empty or duplicated value can't be substituted unambiguously later.
        if value == "" or value_counts.get(value, 0) > 1:
            _log.info("direct_mode_ambiguous_value", group_id=form.group_id, field=field.name)
            return None
        field_values[field.selector] = value

    _log.info("direct_mode_learned", group_id=form.group_id, fields=len(field_values))
    return RequestTemplate(
        method=baseline_request.method,
        url=baseline_request.url,
        content_type=_SIMPLE_CONTENT_TYPE,
        body_template=baseline_request.request_body,
        field_values=field_values,
    )


class DirectExecutor:
    """Fires a FuzzPlan straight over HTTP using a learned RequestTemplate."""

    def __init__(self, session: CaptureSession, template: RequestTemplate) -> None:
        self._session = session
        self._template = template

    async def run(self, plan: FuzzPlan) -> EffectBundle:
        body = self._substitute(plan)
        response = await self._session.request.fetch(
            self._template.url,
            method=self._template.method.value,
            headers={"content-type": self._template.content_type},
            data=body,
        )
        status = response.status
        await response.dispose()
        request = CapturedRequest(
            method=self._template.method,
            url=self._template.url,
            status=status,
            response_kind=ResponseKind.from_status(status),
            request_body=body[:_BODY_PREVIEW_LEN],
            content_type=self._template.content_type,
        )
        return EffectBundle(
            action_id=plan.case_id, tab_id=self._session.tab_id, requests=[request]
        )

    def _substitute(self, plan: FuzzPlan) -> str:
        """Replace the fuzzed field's baseline value with the fuzz case's value,
        leaving every other field at its learned baseline."""
        target_selector = plan.field_under_test.selector
        target_baseline = self._template.field_values.get(target_selector)
        pairs = parse_qsl(self._template.body_template, keep_blank_values=True)
        replaced = False
        out_pairs: list[tuple[str, str]] = []
        for name, value in pairs:
            if not replaced and value == target_baseline:
                out_pairs.append((name, plan.case.value))
                replaced = True
            else:
                out_pairs.append((name, value))
        return urlencode(out_pairs)
