# auth/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

> auth — one-time login recording (record_login) and deterministic replay

## __init__.py
```
# auth — one-time login recording (record_login) and deterministic replay


```

## contracts.py
```
# auth contracts — LoginMacro (a saved, replayable recording of a login form


cls LoginMacro(BaseModel)

cls AuthResult(BaseModel)

```

## recorder.py
```
# record_login — one-time login recording: navigates to a login page, disambiguates

_TOKEN_KEY_CANDIDATES = ('access_token', 'token', 'jwt')

_find_login_form(page_model_forms: list[FormModel) -> FormModel

_username_selector(form: FormModel) -> str

_extract_bearer_token(text: str) -> str | None

async _check_authenticated(session: CaptureSession, login_url: str, success_indicator: str?) -> bool

async record_login(pool: BrowserPool, login_url: str, username: str, password: str) -> tuple[LoginMacro, AuthResult]

```

## replayer.py
```
# replay_login — deterministic replay from a saved LoginMacro: no PageModeler re-run,


async replay_login(pool: BrowserPool, macro: LoginMacro) -> AuthResult

```
