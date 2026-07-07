# demo_target/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

## app.py
```
# Self-contained FastAPI fixture with one signup form — the ONE-question demo target.

_FORM_HTML = …
_ITEMS = …
_SESSION_TOKEN = 'demo-session-abc123'
_LOGIN_HTML = …

async index() -> str

async signup(name: str = Form(...), email: str = Form(...), age: str = Form('')) -> dict[str, object]

async get_item(item_id: int) -> dict[str, object]

async admin_stats() -> dict[str, object]

async protected(session: str? = ...) -> HTMLResponse

async login_form() -> str

async login(username: str = Form(...), password: str = Form(...)) -> HTMLResponse | RedirectResponse

async api_search(q: str = '', limit: int = 10) -> dict[str, object]
  # Bundled OpenAPI-spec route (see openapi.json) — fuzzable query params.

async api_echo(payload: dict[str, str = Body(...)) -> dict[str, object]
  # Bundled OpenAPI-spec route (see openapi.json) — fuzzable JSON body field.

```
