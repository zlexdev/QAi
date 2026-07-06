"""Pipeline contracts — the externally-driven, resumable state-machine seam (Design 2).

Imports ``qai.engine.plugins`` (never the reverse — layering rule from the plan's
``01-logic.md``): ``AgentDirective``/``CheckContext``/``CheckStatus`` are defined in
``qai.engine.plugins.contracts`` because ``CheckContext`` needs ``AgentDirective``
directly, and plugins/ must not depend on pipeline/.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from qai.engine.contracts import CookieSpec, EffectBundle, Finding, PageModel, PluginFinding
from qai.engine.plugins.contracts import AgentDirective, CheckStatus

_FROZEN = ConfigDict(frozen=True, extra="forbid")

__all__ = [
    "AgentDirective",
    "CheckStatus",
    "PentestContext",
    "PipelineState",
    "ReconStepConfig",
    "SecurityHeadersStepConfig",
    "Stage",
    "StepConfig",
    "StepInfo",
    "StepStatus",
]


class ReconStepConfig(BaseModel):
    model_config = _FROZEN
    stage: Literal["recon"] = "recon"
    # No tunables for the pilot's recon stage; the model exists so the discriminated
    # union has a real member, not a placeholder — future fields land here.


class SecurityHeadersStepConfig(BaseModel):
    model_config = _FROZEN
    stage: Literal["security_headers"] = "security_headers"
    required_headers: list[str] | None = None


StepConfig = Annotated[
    ReconStepConfig | SecurityHeadersStepConfig,
    Field(discriminator="stage"),
]


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    SKIPPED = "skipped"
    ERROR = "error"


class StepInfo(BaseModel):
    model_config = _FROZEN
    name: str
    skippable: bool
    status: StepStatus
    duration_ms: float | None = None
    error: str | None = None


class PipelineState(BaseModel):
    model_config = _FROZEN
    session_id: str
    target_url: str
    steps: list[StepInfo]
    cursor: int
    context_summary: dict[str, int]
    last_step_output: list[PluginFinding] = Field(default_factory=list)


@dataclass(slots=True)
class PentestContext:
    """Mutable, threaded through Stage.__call__. NOT a Pydantic model (per patterns.md's
    Pipeline pattern) — but every field is itself JSON-serializable so SessionStore can
    persist it as a JSON blob."""

    target_url: str
    page: PageModel | None
    effects: list[EffectBundle]
    core_findings: list[Finding]
    plugin_findings: list[PluginFinding]
    directives: list[AgentDirective]
    cookies: list[CookieSpec] | None
    repo_path: str | None


class Stage(ABC):
    name: str
    skippable: bool = True
    timeout_s: float = 15.0

    @abstractmethod
    async def __call__(self, ctx: PentestContext) -> PentestContext: ...
