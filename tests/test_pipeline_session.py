"""SqliteSessionStore CRUD + restart-survival: a SECOND store instance pointed at the
same db file must load() the same session_id and get back an equal PentestContext."""

from __future__ import annotations

from pathlib import Path

import pytest

from qai.engine.contracts import PageModel
from qai.engine.errors import UnknownSessionError
from qai.engine.pipeline.contracts import PentestContext, StepInfo, StepStatus
from qai.engine.pipeline.session import SqliteSessionStore

pytestmark = pytest.mark.asyncio


def _ctx() -> PentestContext:
    return PentestContext(
        target_url="https://example.test",
        page=PageModel(url="https://example.test"),
        effects=[],
        core_findings=[],
        plugin_findings=[],
        directives=[],
        cookies=None,
        repo_path=None,
    )


def _steps() -> list[StepInfo]:
    return [
        StepInfo(name="recon", skippable=False, status=StepStatus.PENDING),
        StepInfo(name="security_headers", skippable=True, status=StepStatus.PENDING),
    ]


async def test_create_load_save_delete_round_trip(tmp_path: Path) -> None:
    store = SqliteSessionStore(tmp_path / "sessions.sqlite3")
    session_id = await store.create(_ctx(), _steps())

    ctx, steps, cursor = await store.load(session_id)
    assert ctx.target_url == "https://example.test"
    assert cursor == 0
    assert steps[0].name == "recon"

    ctx.plugin_findings = []
    await store.save(session_id, ctx, steps, cursor=1)
    _, _, cursor2 = await store.load(session_id)
    assert cursor2 == 1

    await store.delete(session_id)
    with pytest.raises(UnknownSessionError):
        await store.load(session_id)


async def test_load_unknown_session_raises(tmp_path: Path) -> None:
    store = SqliteSessionStore(tmp_path / "sessions.sqlite3")
    with pytest.raises(UnknownSessionError):
        await store.load("does-not-exist")


async def test_second_store_instance_survives_restart(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.sqlite3"
    store_a = SqliteSessionStore(db_path)
    session_id = await store_a.create(_ctx(), _steps())

    # Simulate a process restart: a brand new store instance over the same file.
    store_b = SqliteSessionStore(db_path)
    ctx, steps, cursor = await store_b.load(session_id)
    assert ctx.target_url == "https://example.test"
    assert cursor == 0
    assert [s.name for s in steps] == ["recon", "security_headers"]


async def test_directory_is_created_if_missing(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "qai-reports"
    assert not nested.exists()
    SqliteSessionStore(nested / "sessions.sqlite3")
    assert nested.exists()


async def test_reap_idle_pools_closes_stale_pool_but_keeps_sqlite_row(tmp_path: Path) -> None:
    store = SqliteSessionStore(tmp_path / "sessions.sqlite3")
    session_id = await store.create(_ctx(), _steps())

    closed = False

    class _FakePool:
        async def close(self) -> None:
            nonlocal closed
            closed = True

    store.set_pool(session_id, _FakePool())  # type: ignore[arg-type]
    reaped = await store.reap_idle_pools(ttl_seconds=-1)  # everything is "stale"

    assert reaped == [session_id]
    assert closed is True
    assert store.get_pool(session_id) is None
    # The durable row survives reaping — only the live browser is reclaimed (R-6).
    ctx, _, _ = await store.load(session_id)
    assert ctx.target_url == "https://example.test"


async def test_reap_idle_pools_ignores_fresh_pools(tmp_path: Path) -> None:
    store = SqliteSessionStore(tmp_path / "sessions.sqlite3")
    session_id = await store.create(_ctx(), _steps())

    class _FakePool:
        async def close(self) -> None:
            raise AssertionError("a fresh pool must not be reaped")

    store.set_pool(session_id, _FakePool())  # type: ignore[arg-type]
    reaped = await store.reap_idle_pools(ttl_seconds=600)

    assert reaped == []
    assert store.get_pool(session_id) is not None
