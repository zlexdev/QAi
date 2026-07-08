"""auth contracts — LoginMacro (a saved, replayable recording of a login form
submission) and AuthResult (what came back: cookies + optional bearer token).

LoginMacro.password_value is plaintext, not SecretStr: a saved macro file must
round-trip through model_dump_json()/model_validate_json() and replay the REAL
password (pydantic's SecretStr masks even JSON dumps, which would break replay —
a saved macro would silently try to log in with the literal string "**********").
A saved macro file is therefore a credential at rest — treat it like one: don't
commit it, don't share it, store it with the same care as a plaintext password file."""

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
