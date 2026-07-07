"""Self-contained FastAPI fixture with one signup form — the ONE-question demo target.

One field (``name``) is guarded by an unvalidated-at-the-boundary length check that raises
instead of returning 400 — the fuzzer's ``overflow`` case (a 100k-char string) reliably
trips it, giving the MVP a real 5xx to catch and correlate back to this file.

Run: ``uvicorn qai.demo_target.app:app --port 8000``
"""

from __future__ import annotations

from fastapi import Body, Cookie, FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI(title="qai demo target")

_SIGNUPS: list[dict[str, str]] = []

_FORM_HTML = """<!doctype html>
<html><head><title>Signup</title></head>
<body>
<form id="signup-form" action="/signup" method="post">
  <label for="name">Name</label>
  <input id="name" name="name" type="text" required maxlength="1000">
  <label for="email">Email</label>
  <input id="email" name="email" type="email" required>
  <label for="age">Age</label>
  <input id="age" name="age" type="number" min="0" max="120">
  <button type="submit">Sign up</button>
</form>
</body></html>"""


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return _FORM_HTML


@app.post("/signup")
async def signup(name: str = Form(...), email: str = Form(...), age: str = Form("")) -> dict[str, object]:
    # BUG: the client-side maxlength=1000 has no server-side backstop — a name longer
    # than the DB column limit reaches this raise unguarded instead of a graceful 400.
    if len(name) > 1000:
        raise ValueError(f"name exceeds column limit: {len(name)} chars")
    _SIGNUPS.append({"name": name, "email": email, "age": age})
    return {"ok": True, "count": len(_SIGNUPS)}


_ITEMS = {1: {"id": 1, "owner": "alice", "secret": "alice's private note"},
          2: {"id": 2, "owner": "bob", "secret": "bob's private note"},
          3: {"id": 3, "owner": "carol", "secret": "carol's private note"}}


@app.get("/api/items/{item_id}")
async def get_item(item_id: int) -> dict[str, object]:
    # FIXTURE BUG (deliberate, for IdorCheck's test): any session cookie can read ANY
    # item's record — no ownership check at all. Not a real qai bug, a planted fixture.
    if item_id not in _ITEMS:
        return {"error": "not found"}
    return _ITEMS[item_id]


@app.get("/api/admin/stats")
async def admin_stats() -> dict[str, object]:
    # FIXTURE BUG (deliberate, for AuthBypassCheck's test): reachable with NO auth check
    # at all, despite the "/admin/" path implying it should require one. Planted fixture.
    return {"users": len(_ITEMS), "signups": len(_SIGNUPS)}


@app.get("/protected", response_class=HTMLResponse)
async def protected(session: str | None = Cookie(default=None)) -> str:
    # Properly-protected route (contrast fixture for AuthBypassCheck's negative case).
    if session != _SESSION_TOKEN:
        return HTMLResponse("forbidden", status_code=403)
    return "<html><body>welcome, admin</body></html>"


_SESSION_TOKEN = "demo-session-abc123"
_LOGIN_HTML = """<!doctype html>
<html><head><title>Login</title></head>
<body>
<form id="login-form" action="/login" method="post">
  <label for="username">Username</label>
  <input id="username" name="username" type="text" required>
  <label for="password">Password</label>
  <input id="password" name="password" type="password" required>
  <button type="submit">Log in</button>
</form>
</body></html>"""


@app.get("/login", response_class=HTMLResponse)
async def login_form() -> str:
    return _LOGIN_HTML


@app.post("/login", response_model=None)
async def login(
    username: str = Form(...), password: str = Form(...)
) -> HTMLResponse | RedirectResponse:
    if username != "admin" or password != "secret":
        # Stays on /login (no redirect) — the URL-changed success heuristic must see a
        # real difference between a successful and a failed login attempt.
        return HTMLResponse(_LOGIN_HTML, status_code=401)
    response = RedirectResponse(url="/protected", status_code=303)
    response.set_cookie("session", _SESSION_TOKEN)
    return response


@app.get("/api/search")
async def api_search(q: str = "", limit: int = 10) -> dict[str, object]:
    """Bundled OpenAPI-spec route (see openapi.json) — fuzzable query params."""
    return {"query": q, "limit": limit, "results": []}


@app.post("/api/echo")
async def api_echo(payload: dict[str, str] = Body(...)) -> dict[str, object]:
    """Bundled OpenAPI-spec route (see openapi.json) — fuzzable JSON body field."""
    return {"echoed": payload}
