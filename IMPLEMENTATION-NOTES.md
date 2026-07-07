# Implementation notes — deviations from the frozen plan

## Blocker 3 (found during T7 implementation, not caught by 07-verification.md)

**Claim in the plan (`03-types.md`, `07-verification.md` Blocker 2 fix):**
```python
async def _recon(...) -> tuple[PageModel, EffectBundle]:
    async with CaptureSession(...) as session:
        effect = await session.capture("recon", lambda: session.open(url))
        page_model = await modeler.model(session.page)
        return page_model, effect
```
Same recipe given for `ReconStage.__call__` (Path B).

**What's actually wrong:** `CaptureSession.open()` (`qai/engine/capture.py`) calls
`self._reset()` **internally**, right after the page settles and *before* returning —
this is by design for every *other* caller (`_run_worker`'s baseline-then-fuzz loop):
`open()` is meant to give the next fill/submit action a clean "before" snapshot to diff
against, so the navigation's own requests are deliberately thrown away.

`CaptureSession.capture(action_id, action)` also calls `self._reset()`, but *before*
running `action()` — its own reset happens up front, then it expects `action()` to
populate `self._requests` via the response listener, then reads `self._requests` *after*
`action()` returns to build the `EffectBundle`.

Composing them as the plan specifies — `capture("recon", lambda: session.open(url))` —
means: `capture()` resets, `open()` navigates (response listener fills `self._requests`),
then `open()` itself resets `self._requests` back to `[]` *before* `capture()` gets a
chance to read it. **The returned `EffectBundle.requests` is always empty.**

Confirmed empirically: `test_run_scan_with_security_headers_plugin_populates_plugin_findings`
failed with `plugin_findings == []` against `demo_server`, which sends zero security
headers by default (should have produced 4 findings).

**Fix applied (minimal, additive — does not touch any frozen DTO shape):**
`CaptureSession.open()` gains one new keyword-only parameter,
`capture_load: bool = False`. When `True`, `open()` skips its own internal `self._reset()`
call (the dom-error baseline snapshot still happens either way) — leaving the
navigation's requests in `self._requests` for the *caller's* `capture()` wrapper to
consume. Every existing call site (`_run_worker`, `Explorer`, etc.) is unaffected —
they don't pass `capture_load`, so they get the exact same reset-after-open behavior as
before.

`_recon` and `ReconStage` both call:
```python
effect = await session.capture("recon", lambda: session.open(url, capture_load=True))
```

This is a source-level addition to `capture.py` beyond what `02-files.md`/`03-types.md`
listed for that file (they only mention the `response_headers` field addition) — logged
here per the task instructions rather than silently deviating. No DTO/contract shape
changed; `CaptureSession.open`'s public signature grew one optional kwarg.

---

# active-checks-api-scan-auth plan — deviations found during implementation

## Deviation 1 — `run_scan`'s recon session had to stay open through the plugin pass

**Claim in the plan (`01-logic.md` §2, `02-files.md`):** an ACTIVE check's
`ReplayClient` is "bound to the SAME `CaptureSession` recon already opened — no second
browser/session spin-up," and `PluginRunner`'s one call site (`runner.py::_run_plugins`)
"updated in the same task" to take the new `session` param.

**What was actually wrong:** the plan didn't spell out that `run_scan`'s existing
`_recon()` helper opened its OWN `CaptureSession` in a private `async with` block and
returned only `(page_model, effect)` — the session was **already closed** by the time
`_run_plugins()` ran. There was no live session left for an ACTIVE check's
`ReplayClient` to bind to; `PluginRunner(checks, session)` would have needed a session
that no longer existed.

**Fix applied:** restructured `run_scan` so the recon `CaptureSession` is opened in
`run_scan` itself (not inside `_recon`), and `_run_plugins` runs *before* the `async
with` block closes it — `_recon(session, url)` and `_run_plugins(..., session,
safe_mode)` both now take the session as a parameter instead of opening their own.
Behavior for the existing (no-plugins, no-active-checks) path is unchanged — verified
via the full existing test suite (78/78 green) plus the new
`test_run_scan_without_plugins_is_byte_for_byte_backward_compatible` test, unmodified.

## Deviation 2 — `_fuzz_form`/`DirectExecutor` reuse doesn't generalize to API-scan

**Claim in the plan (`01-logic.md` §5, `02-files.md`):** `api_runner.py` "builds the
SAME 5 objects (`session`/`executor`/`analyzer`/`templates`/`correlator`) itself before
calling [`_fuzz_form`] — this is the SAME setup `_run_worker` already does... so
`api_runner.py` can call the SAME loop without duplicating it."

**What's actually wrong:** `_fuzz_form`'s non-UI path (`DirectExecutor`) substitutes a
fuzz value into a **form-urlencoded body string** learned from one baseline UI
submission (`learn_template`/`RequestTemplate.field_values`, keyed by matching a
baseline value verbatim inside the body). An API operation's parameters live in the
URL path (`/items/{id}`), the query string, or a JSON body — none of which match that
substitution shape, and there is no baseline UI submission to learn from in the first
place (API-scan never drives a DOM).

**Fix applied:** `api_runner.py` does NOT call `_fuzz_form`/`DirectExecutor`. It has its
own small `_ApiRequestExecutor` (path/query/JSON-body substitution straight from
`FuzzPlan.values`, fired via `session.request.fetch`) — but still reuses
`DataGenerator` (fuzz-case generation) and `Analyzer` (the oracle) **unmodified**,
which is the actual substance of Decision B/FP-1 (no duplicated fuzz-case-generation or
oracle logic) even though the literal `_fuzz_form` helper isn't the one invoked here.

## Deviation 3 — `ReplayClient.fire`'s "same session/cookies" for IdorCheck needs no
extra param

01-logic.md's original pseudocode for `IdorCheck` calls
`replay.fire(method, mutated_url, headers=original_headers, cookies=<same session>)` —
but the FROZEN `ReplayClient.fire` signature in `03-types.md` (corrected during this
plan's own verification pass) has no `cookies=` parameter, only `strip_auth: bool =
False`. This is not a bug — `strip_auth=False` (the default) already fires through the
session's live cookie jar automatically (Playwright's `APIRequestContext` shares
context cookies), which IS "same session/cookies." `IdorCheck` simply omits any
cookie-related kwarg; no fix needed, logged here so the mismatch between `01-logic.md`'s
pseudocode and the frozen `03-types.md` signature doesn't read as an oversight.

