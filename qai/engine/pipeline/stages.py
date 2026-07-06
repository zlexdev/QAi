"""Pipeline stages — ReconStage (fixed, first) and the generic CheckStage adapter."""

from __future__ import annotations

from qai.engine.capture import CaptureSession
from qai.engine.errors import ReconNotRunError
from qai.engine.modeler import PageModeler
from qai.engine.pipeline.contracts import PentestContext, Stage
from qai.engine.plugins.contracts import Check, CheckContext, CheckStatus
from qai.engine.plugins.runner import run_with_containment


class ReconStage(Stage):
    name = "recon"
    skippable = False  # recon must run at least once — nothing downstream has a page without it

    def __init__(self, session: CaptureSession) -> None:
        self._session = session  # long-lived, owned by the Pipeline/SessionStore, not this Stage

    async def __call__(self, ctx: PentestContext) -> PentestContext:
        effect = await self._session.capture(
            "recon", lambda: self._session.open(ctx.target_url, capture_load=True)
        )
        ctx.page = await PageModeler().model(self._session.page)
        ctx.effects.append(effect)
        return ctx


class CheckStage(Stage):
    """Generic adapter — works for ANY registered Check, not just security_headers."""

    skippable = True

    def __init__(self, check: Check) -> None:
        self._check = check
        self.name = check.name
        self.timeout_s = check.timeout_s

    async def __call__(self, ctx: PentestContext) -> PentestContext:
        if ctx.page is None:
            raise ReconNotRunError(stage=self.name)
        check_ctx = CheckContext(
            page=ctx.page,
            effects=ctx.effects,
            cookies=ctx.cookies,
            repo_path=ctx.repo_path,
            directives=ctx.directives,
        )
        findings, status, _error = await run_with_containment(
            self._check.run(check_ctx, None), self.timeout_s
        )
        if status is CheckStatus.OK:
            ctx.plugin_findings.extend(findings or [])
        # TIMEOUT/ERROR: swallowed here too (containment already logged); the pipeline's
        # StepInfo.status/error is set by Pipeline.step(), not by this Stage.
        return ctx
