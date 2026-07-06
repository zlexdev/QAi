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
