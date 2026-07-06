"""Check-plugin contracts — the seam a pentest-style check family attaches through.

Leaf package like ``qai/engine/fuzzer/``: imports only from ``qai.engine.contracts``,
never from ``qai.engine.pipeline`` or ``qai.engine.runner`` (layering rule, see
``01-logic.md`` in the plan — pipeline imports plugins, never the reverse).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from qai.engine.contracts import CookieSpec, EffectBundle, PageModel, PluginFinding

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class CheckKind(StrEnum):
    PASSIVE = "passive"
    ACTIVE = "active"


class CheckStatus(StrEnum):
    OK = "ok"
    TIMEOUT = "timeout"
    ERROR = "error"


class AgentDirective(BaseModel):
    """The context block an external agent injects between pipeline steps. Defined HERE
    (not in pipeline/contracts.py) because CheckContext needs it directly and plugins/
    must not depend on pipeline/ — pipeline/contracts.py imports it from here instead."""

    model_config = _FROZEN
    notes: str = ""
    focus_selectors: list[str] = Field(default_factory=list)
    focus_params: list[str] = Field(default_factory=list)
    hints: dict[str, str] = Field(default_factory=dict)


class CheckContext(BaseModel):
    model_config = _FROZEN
    page: PageModel
    effects: list[EffectBundle] = Field(default_factory=list)
    cookies: list[CookieSpec] | None = None
    repo_path: str | None = None
    directives: list[AgentDirective] = Field(default_factory=list)
    # NOTE: no `replay` field here — a live ReplayClient handle (future, active checks) is
    # NOT serializable and is passed as a separate function argument to Check.run, never
    # through this frozen DTO. This keeps CheckContext JSON-round-trippable for the
    # SQLite-persisted pipeline path.


class CheckOutcome(BaseModel):
    model_config = _FROZEN
    plugin: str
    status: CheckStatus
    findings: list[PluginFinding] = Field(default_factory=list)
    duration_ms: float
    error: str | None = None


class Check(ABC):
    name: str
    kind: CheckKind
    timeout_s: float = 10.0

    @abstractmethod
    async def run(self, ctx: CheckContext, replay: object | None = None) -> list[PluginFinding]:
        """``replay`` is None for every PASSIVE check (the pilot's only kind). Reserved for
        a future ``ReplayClient`` type once ACTIVE checks ship."""
        ...
