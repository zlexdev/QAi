"""Self-contained FastAPI fixture with one signup form — the ONE-question demo target.

One field (``name``) is guarded by an unvalidated-at-the-boundary length check that raises
instead of returning 400 — the fuzzer's ``overflow`` case (a 100k-char string) reliably
trips it, giving the MVP a real 5xx to catch and correlate back to this file.

Run: ``uvicorn qai.demo_target.app:app --port 8000``
"""

from __future__ import annotations

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse

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
