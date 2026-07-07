"""auth contracts — LoginMacro (a saved, replayable recording of a login form
submission) and AuthResult (what came back: cookies + optional bearer token)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from qai.engine.contracts import _FROZEN, CookieSpec


class LoginMacro(BaseModel):
    model_config = _FROZEN
    login_url: str
    username_selector: str
    password_selector: str
    username_value: str
    password_value: str
    submit_selector: str | None = None
    success_indicator: str | None = None


class AuthResult(BaseModel):
    model_config = _FROZEN
    cookies: list[CookieSpec] = Field(default_factory=list)
    bearer_token: str | None = None
    authenticated: bool
