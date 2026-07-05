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
from qai.engine.contracts import ActionKind, CrawlAction, CrawlBudget, PageModel, StateRef
from qai.engine.logging import get_logger
from qai.engine.modeler import PageModeler
from qai.engine.risk import is_allowlisted, is_destructive
from qai.engine.state import compute_state

_log = get_logger("explorer")
_CLICK_SETTLE_MS = 500


@dataclass(slots=True)
class ExplorerResult:
    visited: list[tuple[StateRef, PageModel]] = field(default_factory=list)
    states: list[StateRef] = field(default_factory=list)
    skipped_destructive: list[CrawlAction] = field(default_factory=list)
    budget_exhausted_by: str | None = None


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

    async def crawl(self, root_url: str) -> ExplorerResult:
        deadline = time.monotonic() + self._budget.wall_clock_seconds
        frontier: deque[tuple[list[CrawlAction], int]] = deque([([], 0)])
        result = ExplorerResult()
        actions_taken = 0

        while frontier:
            if actions_taken >= self._budget.max_actions:
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
                continue

            state = await compute_state(self._session.page)
            seen = self._seen_hash_counts.get(state.dom_hash, 0)
            if seen >= self._budget.trap_repeat_limit:
                _log.info("trap_detected", dom_hash=state.dom_hash, seen=seen)
                continue
            self._seen_hash_counts[state.dom_hash] = seen + 1
            result.states.append(state)

            page_model = await self._modeler.model(self._session.page)
            result.visited.append((state, page_model))
            _log.info(
                "state_visited", url=state.normalized_url, depth=depth, forms=len(page_model.forms)
            )

            if depth >= self._budget.max_depth:
                continue

            for raw in await self._modeler.discover_actions(self._session.page):
                if actions_taken >= self._budget.max_actions:
                    result.budget_exhausted_by = "max_actions"
                    break
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
                actions_taken += 1
                frontier.append(([*path, action], depth + 1))

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
