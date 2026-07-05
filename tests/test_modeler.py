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
