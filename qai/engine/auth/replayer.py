"""replay_login — deterministic replay from a saved LoginMacro: no PageModeler re-run,
just fills the macro's own stored selectors via the same FuzzPlan + FormExecutor path
record_login uses. Cheaper and repeatable against the same app version."""

from __future__ import annotations

from qai.engine.auth.contracts import AuthResult, LoginMacro
from qai.engine.auth.recorder import _check_authenticated, _extract_bearer_token
from qai.engine.capture import BrowserPool, CaptureSession
from qai.engine.contracts import (
    ExpectedOutcome,
    FieldConstraints,
    FieldKind,
    FieldModel,
    FormModel,
    FuzzCase,
    FuzzIntent,
)
from qai.engine.executor import FormExecutor
from qai.engine.fuzzer.generator import FuzzPlan


async def replay_login(pool: BrowserPool, macro: LoginMacro) -> AuthResult:
    async with CaptureSession(pool=pool) as session:
        await session.open(macro.login_url)

        username_field = FieldModel(
            selector=macro.username_selector, kind=FieldKind.TEXT, constraints=FieldConstraints()
        )
        password_field = FieldModel(
            selector=macro.password_selector, kind=FieldKind.PASSWORD, constraints=FieldConstraints()
        )
        form = FormModel(
            group_id="login-replay",
            submit_selector=macro.submit_selector,
            fields=[username_field, password_field],
        )
        plan = FuzzPlan(
            case_id="login-replay",
            field_under_test=username_field,
            case=FuzzCase(
                value=macro.username_value, intent=FuzzIntent.VALID, expect=ExpectedOutcome.ACCEPT
            ),
            values={
                macro.username_selector: macro.username_value,
                macro.password_selector: macro.password_value,
            },
        )
        effect = await FormExecutor(session).run(form, plan)

        authenticated = await _check_authenticated(session, macro.login_url, macro.success_indicator)
        result_cookies = await session.cookies()
        bearer_token = None
        for req in effect.requests:
            if req.request_body:
                bearer_token = _extract_bearer_token(req.request_body)
                if bearer_token:
                    break

    return AuthResult(cookies=result_cookies, bearer_token=bearer_token, authenticated=authenticated)
