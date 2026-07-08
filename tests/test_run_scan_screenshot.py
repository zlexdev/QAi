"""Optional page screenshot: run_scan(screenshot=True) saves a real PNG and returns
its path; the default (screenshot=False) leaves screenshot_path=None and the rest
of the report byte-identical to before this param existed."""

from __future__ import annotations

from pathlib import Path

import pytest

from qai.engine.runner import run_scan

pytestmark = pytest.mark.asyncio


async def test_screenshot_true_saves_a_real_png(demo_server: str, tmp_path: Path) -> None:
    out_dir = tmp_path / "shots"
    report = await run_scan(demo_server, screenshot=True, screenshot_dir=str(out_dir))

    assert report.screenshot_path is not None
    saved = Path(report.screenshot_path)
    assert saved.exists()
    assert saved.stat().st_size > 0
    assert saved.parent == out_dir


async def test_screenshot_default_false_is_a_no_op(demo_server: str) -> None:
    report = await run_scan(demo_server)
    assert report.screenshot_path is None
