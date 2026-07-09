from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from qai.api.errors import JobNotFoundError
from qai.api.schemas import JobKind, JobStatus


@dataclass(slots=True)
class Job:
    job_id: str
    kind: JobKind
    status: JobStatus = JobStatus.PENDING
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class JobStore:
    """In-process job registry backing the async scan/crawl/api-scan/login-record
    routes. Jobs are lost on process restart — acceptable here since each job is a
    re-runnable scan, not a durable business record (see 00-overview.md Risks)."""

    _jobs: dict[str, Job] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _background_tasks: set[asyncio.Task[None]] = field(default_factory=set)

    async def submit(
        self, kind: JobKind, coro_factory: Callable[[], Awaitable[dict[str, Any]]]
    ) -> Job:
        job = Job(job_id=uuid.uuid4().hex, kind=kind)
        async with self._lock:
            self._jobs[job.job_id] = job

        async def _run() -> None:
            job.status = JobStatus.RUNNING
            try:
                job.result = await coro_factory()
                job.status = JobStatus.DONE
            # Job boundary: any engine failure becomes job.error, never crashes the task.
            except Exception as exc:
                job.error = str(exc)
                job.status = JobStatus.ERROR

        task = asyncio.create_task(_run())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return job

    def get(self, job_id: str) -> Job:
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job
