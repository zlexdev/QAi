"""record_login — one-time login recording: navigates to a login page, disambiguates
the login form (exactly one FieldKind.PASSWORD field), fills it via a synthetic
FuzzPlan + the EXISTING FormExecutor (Decision E — no new fill/submit code), and reads
back the resulting cookies/bearer token into a reusable LoginMacro + AuthResult."""

from __future__ import annotations

import json

from qai.engine.auth.contracts import AuthResult, LoginMacro
from qai.engine.capture import BrowserPool, CaptureSession
from qai.engine.contracts import (
    CookieSpec,
    ExpectedOutcome,
    FieldKind,
    FormModel,
    FuzzCase,
    FuzzIntent,
)
from qai.engine.errors import LoginFailedError
from qai.engine.executor import FormExecutor
from qai.engine.fuzzer.generator import FuzzPlan
from qai.engine.modeler import PageModeler

_TOKEN_KEY_CANDIDATES = ("access_token", "token", "jwt")


def _find_login_form(page_model_forms: list[FormModel]) -> FormModel:
    password_forms = [f for f in page_model_forms if any(fld.kind is FieldKind.PASSWORD for fld in f.fields)]
    if len(password_forms) != 1:
        raise LoginFailedError(
            page_model_forms[0].action or "?" if page_model_forms else "?",
            f"expected exactly one form with a password field, found {len(password_forms)}",
        )
    return password_forms[0]


def _username_selector(form: FormModel) -> str:
    for field in form.fields:
        if field.kind is not FieldKind.PASSWORD:
            return field.selector
    raise LoginFailedError(form.action or "?", "login form has no non-password field for a username")


def _extract_bearer_token(text: str) -> str | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    for key in _TOKEN_KEY_CANDIDATES:
        value = data.get(key)
        if isinstance(value, str):
            return value
    return None


async def _check_authenticated(
    session: CaptureSession, login_url: str, success_indicator: str | None
) -> bool:
    if success_indicator is None:
        return session.page.url != login_url
    if success_indicator.startswith(("http://", "https://")) or "/" in success_indicator:
        return success_indicator in session.page.url
    try:
        return await session.page.locator(success_indicator).count() > 0
    except Exception:
        return False


async def record_login(
    pool: BrowserPool,
    login_url: str,
    username: str,
    password: str,
    *,
    success_indicator: str | None = None,
    cookies: list[CookieSpec] | None = None,
) -> tuple[LoginMacro, AuthResult]:
    async with CaptureSession(pool=pool, cookies=cookies) as session:
        await session.open(login_url)
        page_model = await PageModeler().model(session.page)
        form = _find_login_form(page_model.forms)
        password_selector = next(f.selector for f in form.fields if f.kind is FieldKind.PASSWORD)
        username_selector = _username_selector(form)

        plan = FuzzPlan(
            case_id="login",
            field_under_test=next(f for f in form.fields if f.selector == username_selector),
            case=FuzzCase(value=username, intent=FuzzIntent.VALID, expect=ExpectedOutcome.ACCEPT),
            values={username_selector: username, password_selector: password},
        )
        effect = await FormExecutor(session).run(form, plan)

        authenticated = await _check_authenticated(session, login_url, success_indicator)
        if not authenticated:
            raise LoginFailedError(login_url, "success_indicator never matched after submit")

        result_cookies = await session.cookies()
        bearer_token = None
        for req in effect.requests:
            body = req.request_body
            if body:
                bearer_token = _extract_bearer_token(body)
                if bearer_token:
                    break

    macro = LoginMacro(
        login_url=login_url,
        username_selector=username_selector,
        password_selector=password_selector,
        username_value=username,
        password_value=password,
        submit_selector=form.submit_selector,
        success_indicator=success_indicator,
    )
    auth_result = AuthResult(
        cookies=result_cookies, bearer_token=bearer_token, authenticated=authenticated
    )
    return macro, auth_result
