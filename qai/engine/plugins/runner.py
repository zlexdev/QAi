"""Isolation primitive + PluginRunner — bounded fan-out over registered checks.

``run_with_containment`` is shared by BOTH ``PluginRunner`` (the background pass inside
``run_scan``) and ``CheckStage`` (the externally-driven pipeline) so the timeout+catch-all
shape is written once.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable

from qai.engine.capture import CaptureSession
from qai.engine.logging import get_logger
from qai.engine.plugins.contracts import Check, CheckContext, CheckKind, CheckOutcome, CheckStatus
from qai.engine.plugins.replay import ReplayClient

_log = get_logger("plugins.runner")


async def run_with_containment[T](
    coro: Awaitable[T], timeout_s: float
) -> tuple[T | None, CheckStatus, str | None]:
    """Returns ``(result_or_None, status, error_message_or_None)`` — never raises."""
    try:
        result = await asyncio.wait_for(coro, timeout=timeout_s)
        return result, CheckStatus.OK, None
    except TimeoutError:
        return None, CheckStatus.TIMEOUT, f"exceeded {timeout_s}s"
    except Exception as exc:  # plugin sandbox boundary — must never crash the scan
        _log.exception("check_failed", error=str(exc))
        return None, CheckStatus.ERROR, str(exc)


class PluginRunner:
    def __init__(self, checks: list[Check], session: CaptureSession) -> None:
        self._checks = checks
        self._session = session

    async def run(self, ctx: CheckContext) -> list[CheckOutcome]:
        async def _one(check: Check) -> CheckOutcome:
            if check.kind is CheckKind.ACTIVE and ctx.safe_mode:
                return CheckOutcome(
                    plugin=check.name,
                    status=CheckStatus.SKIPPED,
                    findings=[],
                    duration_ms=0.0,
                    error="active check skipped: safe_mode",
                )
            start = time.monotonic()
            replay = ReplayClient(self._session) if check.kind is CheckKind.ACTIVE else None
            findings, status, error = await run_with_containment(
                check.run(ctx, replay), check.timeout_s
            )
            return CheckOutcome(
                plugin=check.name,
                status=status,
                findings=findings or [],
                duration_ms=(time.monotonic() - start) * 1000,
                error=error,
            )

        # Safe WITHOUT return_exceptions=True: _one() itself never raises, because
        # run_with_containment already caught everything. Satisfies "never bare gather"
        # by construction, not by the flag.
        return list(await asyncio.gather(*(_one(c) for c in self._checks)))
