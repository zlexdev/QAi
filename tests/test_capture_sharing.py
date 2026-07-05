from __future__ import annotations

import asyncio

import pytest

from qai.engine.capture import BrowserPool, CaptureSession

pytestmark = pytest.mark.asyncio


async def test_sessions_on_one_pool_run_sequentially_without_interference() -> None:
    pool = await BrowserPool.create(headless=True)
    try:
        async with CaptureSession(run_id="a", tab_id="a", pool=pool) as s1:
            await s1.page.set_content("<div id='x'>1</div>")
            val1 = await s1.page.eval_on_selector("#x", "e => e.innerText")

        # Closing s1's context must not tear down the shared browser/playwright.
        async with CaptureSession(run_id="b", tab_id="b", pool=pool) as s2:
            await s2.page.set_content("<div id='x'>2</div>")
            val2 = await s2.page.eval_on_selector("#x", "e => e.innerText")
    finally:
        await pool.close()

    assert val1 == "1"
    assert val2 == "2"


async def test_concurrent_sessions_on_one_pool_have_isolated_state() -> None:
    pool = await BrowserPool.create(headless=True)

    async def run(tag: str) -> str:
        async with CaptureSession(run_id=tag, tab_id=tag, pool=pool) as session:
            await session.page.set_content(f"<div id='x'>{tag}</div>")
            await session.page.wait_for_timeout(50)
            result: str = await session.page.eval_on_selector("#x", "e => e.innerText")
            return result

    try:
        results = await asyncio.gather(run("alpha"), run("beta"))
    finally:
        await pool.close()

    assert set(results) == {"alpha", "beta"}
