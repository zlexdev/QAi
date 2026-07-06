"""Typed errors carrying arguments, never pre-formatted text. Never silenced upstream."""

from __future__ import annotations


class QaiError(Exception):
    """Base for every engine error."""


class InvalidTargetError(QaiError):
    """The URL or repo path failed boundary validation."""

    def __init__(self, value: str, reason: str) -> None:
        super().__init__(f"invalid target {value!r}: {reason}")
        self.value = value
        self.reason = reason


class CaptureError(QaiError):
    """Browser/CDP navigation or capture failed after retries."""

    def __init__(self, url: str, cause: str) -> None:
        super().__init__(f"capture failed for {url!r}: {cause}")
        self.url = url
        self.cause = cause


class InvalidCookieSpecError(QaiError):
    """A ``--cookie``/MCP cookie argument didn't match ``domain:name=value``."""

    def __init__(self, raw: str, reason: str) -> None:
        super().__init__(f"invalid cookie spec {raw!r}: {reason}")
        self.raw = raw
        self.reason = reason


class RouteResolveError(QaiError):
    """A captured request could not be resolved to a source route."""

    def __init__(self, route: str | None, cause: str) -> None:
        super().__init__(f"route resolve failed for {route!r}: {cause}")
        self.route = route
        self.cause = cause


class UnknownCheckError(QaiError):
    """A ``plugins=[...]`` entry doesn't match any registered check."""

    def __init__(self, name: str, available: list[str]) -> None:
        super().__init__(f"unknown check {name!r}, available: {available}")
        self.name = name
        self.available = available


class UnknownSessionError(QaiError):
    """A pipeline session_id has no matching SQLite row (never existed, expired, or aborted)."""

    def __init__(self, session_id: str) -> None:
        super().__init__(f"unknown or expired pipeline session {session_id!r}")
        self.session_id = session_id


class InvalidStepConfigError(QaiError):
    """A ``config`` payload's ``stage`` discriminator doesn't match the pipeline's current stage."""

    def __init__(self, expected_stage: str, got_stage: str) -> None:
        super().__init__(
            f"config for stage {got_stage!r} does not match current stage {expected_stage!r}"
        )
        self.expected_stage = expected_stage
        self.got_stage = got_stage
