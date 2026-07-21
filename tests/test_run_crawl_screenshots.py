"""Full-crawl screenshot export: run_crawl(screenshot=True) saves one real PNG per
VISITED state — including pages with no form, which the fuzz phase skips entirely —
and reports every url->path pair. The default leaves the report byte-identical."""

from __future__ import annotations

from pathlib import Path

import pytest

from qai.engine.contracts import CrawlBudget
from qai.engine.runner import run_crawl

pytestmark = pytest.mark.asyncio


async def test_screenshot_true_saves_a_png_per_visited_page(
    demo_server: str, tmp_path: Path
) -> None:
    out_dir = tmp_path / "shots"
    report = await run_crawl(
        demo_server,
        budget=CrawlBudget(max_depth=1, max_actions=5, wall_clock_seconds=60),
        safe_mode=True,
        screenshot=True,
        screenshot_dir=str(out_dir),
    )

    assert report.screenshots, "crawl visited pages but exported no screenshots"
    # One shot per visited state, not per page-with-a-form: the fuzz phase drops
    # form-less pages and this export must not inherit that filter.
    assert len(report.screenshots) == len(report.states_visited)
    for shot in report.screenshots:
        saved = Path(shot.path)
        assert saved.exists(), f"{shot.url} reported a path that isn't on disk"
        assert saved.stat().st_size > 0
        assert saved.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    # Each run gets its own subdirectory so repeat crawls never overwrite each other.
    assert {Path(s.path).parent for s in report.screenshots} == {out_dir / report.run_id}
    assert len({Path(s.path).name for s in report.screenshots}) == len(report.screenshots)


async def test_screenshot_default_false_is_a_no_op(demo_server: str, tmp_path: Path) -> None:
    report = await run_crawl(
        demo_server,
        budget=CrawlBudget(max_depth=1, max_actions=3, wall_clock_seconds=60),
        safe_mode=True,
        screenshot_dir=str(tmp_path / "shots"),
    )
    assert report.screenshots == []
    assert not (tmp_path / "shots").exists()
