"""FormExecutor — fills a form per a FuzzPlan and submits it, driving CaptureSession."""

from __future__ import annotations

from qai.engine.capture import CaptureSession
from qai.engine.contracts import EffectBundle, FieldKind, FormModel
from qai.engine.fuzzer.generator import FuzzPlan
from qai.engine.logging import get_logger

_log = get_logger("executor")

_TEXT_LIKE = {
    FieldKind.TEXT,
    FieldKind.TEXTAREA,
    FieldKind.PASSWORD,
    FieldKind.EMAIL,
    FieldKind.NUMBER,
    FieldKind.DATE,
    FieldKind.UNKNOWN,
}


class FormExecutor:
    """Fills every field in ``form`` with ``plan.values`` then submits it."""

    def __init__(self, session: CaptureSession) -> None:
        self._session = session

    async def run(self, form: FormModel, plan: FuzzPlan) -> EffectBundle:
        async def action() -> None:
            for field in form.fields:
                value = plan.values.get(field.selector, "")
                await self._fill(field.selector, field.kind, value)
            if form.submit_selector:
                await self._session.page.click(form.submit_selector, timeout=5_000)
            else:
                await self._session.page.keyboard.press("Enter")

        return await self._session.capture(plan.case_id, action)

    async def _fill(self, selector: str, kind: FieldKind, value: str) -> None:
        page = self._session.page
        try:
            if kind in _TEXT_LIKE:
                await self._neutralize_constraints(selector)
                await page.fill(selector, value, timeout=3_000)
            elif kind is FieldKind.SELECT:
                if value:
                    await page.select_option(selector, value=value, timeout=3_000)
            elif kind in {FieldKind.CHECKBOX, FieldKind.RADIO}:
                if value == "on":
                    await page.check(selector, timeout=3_000)
                else:
                    await page.uncheck(selector, timeout=3_000)
            # FILE: skipped in MVP (strategies.FileStrategy yields no cases).
        except Exception as exc:
            _log.warning("fill_failed", selector=selector, error=str(exc))

    async def _neutralize_constraints(self, selector: str) -> None:
        """Strip client-side guards that would swallow a fuzz payload before it ships.

        ``maxlength``/``pattern``/``type=number`` are HTML5 UX guards enforced by the
        browser itself (Playwright's ``fill`` honors them) — an overflow/malicious case
        that never leaves the DOM proves nothing about the *server's* validation, which
        is the oracle this tool actually cares about (see PLAN.md Analyzer oracle).
        """
        try:
            await self._session.page.eval_on_selector(
                selector,
                """el => {
                    el.removeAttribute('maxlength');
                    el.removeAttribute('pattern');
                    el.removeAttribute('minlength');
                    if (el.tagName.toLowerCase() === 'input'
                        && ['number','email','date','range'].includes(el.type)) {
                        el.type = 'text';
                    }
                }""",
            )
        except Exception as exc:  # best-effort; fill() below still runs even if this fails
            _log.warning("neutralize_failed", selector=selector, error=str(exc))
