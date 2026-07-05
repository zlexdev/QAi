from __future__ import annotations

import pytest

from qai.engine.capture import CaptureSession
from qai.engine.contracts import FieldKind
from qai.engine.modeler import PageModeler

pytestmark = pytest.mark.asyncio

_RANGE_HTML = """<!doctype html>
<html><body>
<form id="roi-form">
  <input id="roi" type="range" min="1" max="200" step="1" value="30" aria-label="Orders per day">
  <button type="submit">Go</button>
</form>
</body></html>"""


async def test_range_input_is_modeled_as_number_field() -> None:
    """type=range is semantically numeric (min/max/step) — misclassifying it as
    text/unknown sends non-numeric fuzz values the browser silently refuses to type,
    so the field never actually gets fuzzed (found live on chazer.chqcode.dev)."""
    async with CaptureSession(headless=True, run_id="test") as session:
        await session.page.set_content(_RANGE_HTML)
        model = await PageModeler().model(session.page)

    assert len(model.forms) == 1
    field = model.forms[0].fields[0]
    assert field.kind is FieldKind.NUMBER
    assert field.constraints.minimum == 1
    assert field.constraints.maximum == 200


_HIDDEN_CLONE_HTML = """<!doctype html>
<html><body>
<form id="search-form">
  <input id="real" type="text" name="q" aria-label="Search">
  <input id="clone" type="text" name="q_clone" tabindex="-1" aria-hidden="true">
  <input id="cssHidden" type="text" name="q_css" style="display:none">
  <button type="submit">Go</button>
</form>
</body></html>"""


async def test_aria_hidden_and_css_hidden_fields_are_excluded() -> None:
    """A visually-hidden 'focus catcher' clone is a real DOM node the executor can
    never fill/click — Playwright times out on every fuzz case against it, burning
    most of a run's time budget on one broken field (found live on a real site's
    mobile-header search clone)."""
    async with CaptureSession(headless=True, run_id="test") as session:
        await session.page.set_content(_HIDDEN_CLONE_HTML)
        model = await PageModeler().model(session.page)

    assert len(model.forms) == 1
    names = {f.name for f in model.forms[0].fields}
    assert names == {"q"}
