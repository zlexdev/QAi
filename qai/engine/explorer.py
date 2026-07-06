"""Explorer — the state-graph crawler's outer loop.

Reuses every Phase 0-3 piece unchanged (PageModeler, DataGenerator, FormExecutor,
Analyzer, CodeCorrelator) — this module only adds the *outer* loop deciding which
pages/states to visit. BFS frontier (shallow-first: better budget usage than DFS —
covers breadth of the app before depth of one branch), structural-DOM-hash dedup,
checkpoint+replay (a URL alone can't identify SPA in-memory state), and hard budgets.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from qai.engine.capture import CaptureSession
from qai.engine.contracts import (
    ActionKind,
    CrawlAction,
    CrawlBudget,
    PageModel,
    SkippedPage,
    SkipReason,
    StateRef,
)
from qai.engine.logging import get_logger
from qai.engine.modeler import PageModeler
from qai.engine.risk import is_allowlisted, is_destructive
from qai.engine.state import compute_state, normalize_url, url_template

_log = get_logger("explorer")
_CLICK_SETTLE_MS = 500
_UNKNOWN_TARGET = "(unknown — SPA action chain, not a direct link)"
# Safety valve independent of max_actions — a page with hundreds of unique links
# shouldn't grow the frontier unbounded while max_actions still counts *visited*
# pages one at a time.
_FRONTIER_SAFETY_CAP = 2000


@dataclass(slots=True)
class ExplorerResult:
    visited: list[tuple[StateRef, PageModel]] = field(default_factory=list)
    states: list[StateRef] = field(default_factory=list)
    skipped_destructive: list[CrawlAction] = field(default_factory=list)
    not_visited: list[SkippedPage] = field(default_factory=list)
    budget_exhausted_by: str | None = None


def _target_of(path: list[CrawlAction]) -> str:
    if path and path[-1].kind is ActionKind.LINK and path[-1].href:
        return path[-1].href
    return _UNKNOWN_TARGET


class Explorer:
    """Crawls same-origin states reachable from a root URL, within a CrawlBudget."""

    def __init__(
        self,
        session: CaptureSession,
        budget: CrawlBudget,
        *,
        allowlist: frozenset[str] = frozenset(),
    ) -> None:
        self._session = session
        self._budget = budget
        self._allowlist = allowlist
        self._modeler = PageModeler()
        self._seen_hash_counts: dict[str, int] = {}
        self._template_counts: dict[str, int] = {}
        # Set once at construction, not inside crawl(), so run_crawl's post-discovery
        # fuzz phase can share this same absolute deadline instead of the wall-clock
        # budget only ever bounding discovery (fuzzing pages already found could still
        # run unbounded past it).
        self.deadline = time.monotonic() + budget.wall_clock_seconds

    async def crawl(self, root_url: str) -> ExplorerResult:
        deadline = self.deadline
        frontier: deque[tuple[list[CrawlAction], int]] = deque([([], 0)])
        result = ExplorerResult()
        # max_actions counts pages actually VISITED (root doesn't count against it),
        # not pages merely discovered — a nav menu with 30 links must not exhaust the
        # whole budget before the crawler ever leaves the root page.
        visited_count = 0
        # Dedups discovered links before queueing — a header/footer/mobile-nav trio
        # linking to the same URL three times must not burn 3x the budget on one target.
        queued_urls: set[str] = {normalize_url(root_url)}

        while frontier:
            if visited_count >= self._budget.max_actions:
                result.budget_exhausted_by = "max_actions"
                break
            if time.monotonic() >= deadline:
                result.budget_exhausted_by = "wall_clock"
                break

            path, depth = frontier.popleft()
            try:
                await self._restore(root_url, path)
            except Exception as exc:
                _log.warning("replay_failed", path_len=len(path), error=str(exc))
                result.not_visited.append(
                    SkippedPage(url=_target_of(path), reason=SkipReason.REPLAY_FAILED)
                )
                continue

            state = await compute_state(self._session.page)
            seen = self._seen_hash_counts.get(state.dom_hash, 0)
            if seen >= self._budget.trap_repeat_limit:
                _log.info("trap_detected", dom_hash=state.dom_hash, seen=seen)
                result.not_visited.append(
                    SkippedPage(url=state.normalized_url, reason=SkipReason.TRAP_DETECTED)
                )
                continue
            self._seen_hash_counts[state.dom_hash] = seen + 1
            result.states.append(state)
            if depth > 0:
                visited_count += 1

            page_model = await self._modeler.model(self._session.page)
            result.visited.append((state, page_model))
            _log.info(
                "state_visited", url=state.normalized_url, depth=depth, forms=len(page_model.forms)
            )

            if depth >= self._budget.max_depth:
                continue

            for raw in await self._modeler.discover_actions(self._session.page):
                if len(frontier) >= _FRONTIER_SAFETY_CAP:
                    break
                if raw["kind"] == ActionKind.LINK.value and raw.get("href"):
                    norm = normalize_url(raw["href"])
                    if norm in queued_urls:
                        continue
                    queued_urls.add(norm)
                    template = url_template(norm)
                    template_seen = self._template_counts.get(template, 0)
                    if template_seen >= self._budget.max_pages_per_template:
                        result.not_visited.append(
                            SkippedPage(url=norm, reason=SkipReason.DUPLICATE_TEMPLATE)
                        )
                        _log.info("duplicate_template_skipped", url=norm, template=template)
                        continue
                    self._template_counts[template] = template_seen + 1
                action = CrawlAction(
                    kind=ActionKind(raw["kind"]),
                    selector=raw["selector"],
                    href=raw.get("href"),
                    label=raw.get("label"),
                    destructive=is_destructive(raw.get("label")),
                )
                if action.destructive and not is_allowlisted(action.selector, self._allowlist):
                    result.skipped_destructive.append(action)
                    _log.info("destructive_skipped", selector=action.selector, label=action.label)
                    continue
                frontier.append(([*path, action], depth + 1))

        if result.budget_exhausted_by is not None and frontier:
            reason = (
                SkipReason.BUDGET_WALL_CLOCK
                if result.budget_exhausted_by == "wall_clock"
                else SkipReason.BUDGET_MAX_ACTIONS
            )
            result.not_visited.extend(
                SkippedPage(url=_target_of(path), reason=reason) for path, _depth in frontier
            )

        return result

    async def _restore(self, root_url: str, path: list[CrawlAction]) -> None:
        """Replay the action path from the root checkpoint. Links replay via direct
        navigation (robust — selectors can shift between visits); buttons replay via
        click (the only way to trigger SPA-only state changes)."""
        await self._session.open(root_url)
        for action in path:
            if action.kind is ActionKind.LINK and action.href:
                await self._session.page.goto(
                    action.href, timeout=15_000, wait_until="domcontentloaded"
                )
            else:
                await self._session.page.click(action.selector, timeout=5_000)
            await self._session.page.wait_for_timeout(_CLICK_SETTLE_MS)
