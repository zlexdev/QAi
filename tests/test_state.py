from __future__ import annotations

import pytest

from qai.engine.capture import CaptureSession
from qai.engine.state import compute_state, normalize_url


def test_normalize_url_strips_fragment_and_trailing_slash() -> None:
    assert normalize_url("http://x/a/#section") == normalize_url("http://x/a")


@pytest.mark.asyncio
async def test_same_structure_different_text_yields_same_hash() -> None:
    async with CaptureSession(headless=True, run_id="t") as session:
        await session.page.set_content("<body><div><p>Hello</p></div></body>")
        a = await compute_state(session.page)
        await session.page.set_content("<body><div><p>Goodbye world</p></div></body>")
        b = await compute_state(session.page)
    assert a.dom_hash == b.dom_hash


@pytest.mark.asyncio
async def test_different_structure_yields_different_hash() -> None:
    async with CaptureSession(headless=True, run_id="t") as session:
        await session.page.set_content("<body><div><p>Hello</p></div></body>")
        a = await compute_state(session.page)
        await session.page.set_content("<body><div><p>Hello</p><span>x</span></div></body>")
        b = await compute_state(session.page)
    assert a.dom_hash != b.dom_hash
