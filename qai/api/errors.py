from __future__ import annotations


class JobNotFoundError(Exception):
    """No job with this id was ever submitted, or the process restarted (jobs are
    in-memory only — see 00-overview.md Risks)."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        super().__init__(f"unknown job {job_id!r}")


class InvalidApiKeyError(Exception):
    """``X-API-Key`` header missing or not equal to ``Settings.api_key``."""
