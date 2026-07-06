"""SessionStore — persists PentestContext/StepInfo/cursor to SQLite so a driven pipeline
session survives an MCP server restart. The live BrowserPool/Page itself cannot be
persisted (a live Playwright process handle) — see 05-risks.md R-3: the in-process
``_live_pools`` side-channel is allowed to be lost on restart; the next qa_pipeline_step
call transparently re-opens a fresh CaptureSession at ctx.target_url.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict
from pathlib import Path

from qai.engine.capture import BrowserPool
from qai.engine.contracts import CookieSpec, EffectBundle, Finding, PageModel, PluginFinding
from qai.engine.errors import UnknownSessionError
from qai.engine.pipeline.contracts import AgentDirective, PentestContext, StepInfo

# YAGNI per code-quality rules: a single hardcoded idle-TTL, no Settings knob until a
# second call site needs a different value (05-risks.md R-6's documented default).
IDLE_TTL_SECONDS = 600


class SessionStore(ABC):
    @abstractmethod
    async def create(self, ctx: PentestContext, steps: list[StepInfo]) -> str: ...

    @abstractmethod
    async def load(self, session_id: str) -> tuple[PentestContext, list[StepInfo], int]: ...

    @abstractmethod
    async def save(
        self, session_id: str, ctx: PentestContext, steps: list[StepInfo], cursor: int
    ) -> None: ...

    @abstractmethod
    async def delete(self, session_id: str) -> None: ...


def _ctx_to_json(ctx: PentestContext) -> str:
    payload = asdict(ctx)
    payload["page"] = ctx.page.model_dump(mode="json") if ctx.page is not None else None
    payload["effects"] = [e.model_dump(mode="json") for e in ctx.effects]
    payload["core_findings"] = [f.model_dump(mode="json") for f in ctx.core_findings]
    payload["plugin_findings"] = [f.model_dump(mode="json") for f in ctx.plugin_findings]
    payload["directives"] = [d.model_dump(mode="json") for d in ctx.directives]
    payload["cookies"] = [c.model_dump(mode="json") for c in ctx.cookies] if ctx.cookies else None
    return json.dumps(payload)


def _ctx_from_json(raw: str) -> PentestContext:
    payload = json.loads(raw)
    return PentestContext(
        target_url=payload["target_url"],
        page=PageModel.model_validate(payload["page"]) if payload["page"] is not None else None,
        effects=[EffectBundle.model_validate(e) for e in payload["effects"]],
        core_findings=[Finding.model_validate(f) for f in payload["core_findings"]],
        plugin_findings=[PluginFinding.model_validate(f) for f in payload["plugin_findings"]],
        directives=[AgentDirective.model_validate(d) for d in payload["directives"]],
        cookies=(
            [CookieSpec.model_validate(c) for c in payload["cookies"]]
            if payload["cookies"] is not None
            else None
        ),
        repo_path=payload["repo_path"],
    )


class SqliteSessionStore(SessionStore):
    """One table: sessions(session_id TEXT PRIMARY KEY, ctx_json TEXT, steps_json TEXT,
    cursor INTEGER, updated_at TEXT). Every field of PentestContext/StepInfo is already
    JSON-serializable (Pydantic models / plain values), so this is a straightforward
    JSON blob, no custom serializer needed.

    Also owns the in-process ``_live_pools`` side-channel: BrowserPool instances are
    NOT persisted here (a live Playwright handle can't survive a restart) — callers use
    ``get_pool``/``set_pool``/``evict_pool`` to track the live browser alongside the
    durable SQLite row.
    """

    def __init__(self, db_path: Path) -> None:
        # W3.5 correction 3 — the MCP server never creates qai-reports/ itself (only
        # the CLI's --auto-report path does); this store must not assume it exists.
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                ctx_json TEXT NOT NULL,
                steps_json TEXT NOT NULL,
                cursor INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        self._conn.commit()
        # session_id -> (BrowserPool, last_touched_monotonic) — not persisted, see R-3/R-6.
        self._live_pools: dict[str, tuple[BrowserPool, float]] = {}

    async def create(self, ctx: PentestContext, steps: list[StepInfo]) -> str:
        session_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO sessions (session_id, ctx_json, steps_json, cursor, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, _ctx_to_json(ctx), json.dumps([s.model_dump(mode="json") for s in steps]), 0, time.time()),
        )
        self._conn.commit()
        return session_id

    async def load(self, session_id: str) -> tuple[PentestContext, list[StepInfo], int]:
        row = self._conn.execute(
            "SELECT ctx_json, steps_json, cursor FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise UnknownSessionError(session_id)
        ctx_json, steps_json, cursor = row
        ctx = _ctx_from_json(ctx_json)
        steps = [StepInfo.model_validate(s) for s in json.loads(steps_json)]
        return ctx, steps, cursor

    async def save(
        self, session_id: str, ctx: PentestContext, steps: list[StepInfo], cursor: int
    ) -> None:
        cur = self._conn.execute(
            "UPDATE sessions SET ctx_json = ?, steps_json = ?, cursor = ?, updated_at = ? "
            "WHERE session_id = ?",
            (
                _ctx_to_json(ctx),
                json.dumps([s.model_dump(mode="json") for s in steps]),
                cursor,
                time.time(),
                session_id,
            ),
        )
        self._conn.commit()
        if cur.rowcount == 0:
            raise UnknownSessionError(session_id)

    async def delete(self, session_id: str) -> None:
        self._conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        self._conn.commit()
        self._live_pools.pop(session_id, None)

    def get_pool(self, session_id: str) -> BrowserPool | None:
        entry = self._live_pools.get(session_id)
        if entry is None:
            return None
        pool, _ = entry
        self._live_pools[session_id] = (pool, time.monotonic())
        return pool

    def set_pool(self, session_id: str, pool: BrowserPool) -> None:
        self._live_pools[session_id] = (pool, time.monotonic())

    def evict_pool(self, session_id: str) -> BrowserPool | None:
        entry = self._live_pools.pop(session_id, None)
        return entry[0] if entry else None

    async def reap_idle_pools(self, ttl_seconds: float = IDLE_TTL_SECONDS) -> list[str]:
        """Closes and evicts any BrowserPool untouched for longer than ``ttl_seconds``
        (R-6 mitigation). The SQLite row survives — a later qa_pipeline_step still
        resumes per R-3's re-open path; only the live browser process is reclaimed.
        Returns the session_ids reaped, for logging/testing."""
        now = time.monotonic()
        stale = [sid for sid, (_, touched) in self._live_pools.items() if now - touched > ttl_seconds]
        for sid in stale:
            pool = self.evict_pool(sid)
            if pool is not None:
                await pool.close()
        return stale
