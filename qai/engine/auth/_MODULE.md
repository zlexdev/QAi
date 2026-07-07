# auth

One-time login recording (`record_login`) and deterministic replay (`replay_login`),
producing an `AuthResult` (cookies + optional bearer token) that feeds the engine's
EXISTING `cookies=`/`default_headers` mechanisms — no second auth pipe (Decision C).

## Public surface
- `contracts.py` — `LoginMacro` (JSON-serializable, saved/loaded by the CLI/MCP
  caller), `AuthResult`.
- `recorder.py` — `record_login(pool, login_url, username, password, *,
  success_indicator=None, cookies=None) -> tuple[LoginMacro, AuthResult]`. Disambiguates
  the login form by requiring exactly one `FieldKind.PASSWORD` field on the page;
  raises `LoginFailedError` if zero/2+ or if `success_indicator` never matches.
- `replayer.py` — `replay_login(pool, macro) -> AuthResult`. Uses the macro's stored
  selectors directly — no `PageModeler` re-run, cheaper and deterministic on repeat runs.

## Reuse, not new fill/submit code (Decision E)
Both build a synthetic `FuzzPlan` (username field as the nominal `field_under_test`,
`values` carrying username+password) and call the EXISTING
`FormExecutor(session).run(form, plan)` — the login form is filled/submitted through
the SAME code path every other form is.

## Known v1 limitations (see plan `05-risks.md`)
- Single-page username+password POST form only — multi-step SSO logins raise
  `LoginFailedError` (no `FieldKind.PASSWORD` field found on the given URL).
- Bearer-token detection is a best-effort heuristic (scans JSON request bodies for
  `access_token`/`token`/`jwt` keys) — a caller needing a specific token shape can
  bypass recording and pass a bearer value directly via `CaptureSession`'s
  `default_headers`.
