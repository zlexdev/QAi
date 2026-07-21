---
name: qai
description: Run QAi — the autonomous QA fuzzer that scans web forms and APIs and points at the file:line where a bug lives. Use when asked to scan/fuzz/QA-test a site or API, crawl a staging app for broken forms, screenshot every page of a site, check an OpenAPI/GraphQL spec, or read a qai report. Triggers — "прогони qai", "проскань сайт", "profuzz форму", "найди баги на стейдже", "обойди все страницы", "скриншоты всех страниц", "scan this URL", "fuzz the signup form", "qai crawl", "qa_scan", "qa_crawl".
---

# QAi

Fuzzes every field on a page, watches what breaks, and maps the break back to a line
in your repo.

**It is a QA validator, not a pentest tool.** The question it asks is "does this input
crash the app", not "can I break in". IDOR / auth-bypass / security-header checks exist
but are opt-in extras on the same engine.

## The safety gate — read before running anything

Any host that is not `localhost` / `127.0.0.1` / `::1` runs in **safe mode** unless you
pass `--i-own-this-target` (CLI) or `own_target=True` (MCP/REST).

Safe mode is **not** a dry run of the fuzzer. It models the page and stops.
No field is filled. No request is submitted. You get an inventory, not a scan.

So a run that reports zero findings against a remote host has probably found nothing
because it never fuzzed. Check `safe_mode` in the report before believing a clean result.

Passing the flag is you asserting you are authorised to fuzz that host. QAi cannot
verify that, and never checks.

## Which surface

Three ways in, same engine behind all of them.

**CLI** — one-off runs, local work, CI.
**MCP** (`qa_*` tools) — an agent runs the scan and opens the offending file in one
session. This is the surface worth reaching for inside Claude Code.
**REST** (`/v1/*`, `X-API-Key`) — a remote box does the browser work. Jobs are async:
POST returns `202` + a `job_id`, then poll `GET /v1/jobs/{job_id}` until `status` is
`done` or `error`.

## Scan one page

```bash
uv run qai http://127.0.0.1:8000 --repo ./my-app --html report.html
```

`--repo` is what turns a finding into `app.py:47`. Without it you still get findings,
just no source location.

A `.json` + `.md` report lands in `qai-reports/` on every run unless you pass
`--no-auto-report`. `--json` / `--html` write to a path you choose.

Exit codes: `0` clean, `2` findings exist, `1` a QAi error (bad URL, missing repo,
capture failure).

## Crawl a whole app

```bash
uv run qai https://staging.example.com --repo ./my-app --i-own-this-target \
  --crawl --max-depth 3 --max-actions 100 --wall-clock 600
```

Breadth-first over same-origin pages, then the fuzz pass on every page that has a form.

Budgets — `--max-depth` (2), `--max-actions` (50), `--wall-clock` (300s). Hitting one is
reported as `budget_exhausted_by`, never a silent truncation. `--max-actions` counts
pages actually **visited**, so a nav menu with 30 duplicate links does not eat the budget.

Off-host links are never followed. `--allowed-domain HOST` (repeatable) adds a host that
is not a subdomain of the root — a separate SSO or API domain. `--no-subdomains` narrows
to the exact root host.

Links and buttons whose text matches a destructive keyword (delete / pay / withdraw /
удалить / оплатить / …) are never clicked. `--allow-destructive SELECTOR` permits one
specific control. This is a keyword heuristic, not a guarantee — read
`skipped_destructive` in the report rather than assuming nothing dangerous was touched.

## Screenshot every page

```bash
uv run qai http://127.0.0.1:8000 --crawl --screenshot --screenshot-dir shots
```

With `--crawl`, one PNG per **visited page**, pages without forms included — the fuzz
pass skips those, the screenshot pass does not.

Without `--crawl`, `--screenshot` saves a single PNG of the recon page.

Files go to `<dir>/<run_id>/<ordinal>-<slug>.png`, sorted in visit order, one
subdirectory per run so repeat crawls do not overwrite each other. The report's
`screenshots` array carries the url → path pairs.

A failed shot is logged and skipped, never fatal. `screenshots` can be shorter than
`states_visited` — trust the array, not the page count.

## Behind a login

Two options, both injected before any navigation.

Cookies, when you already have a session:

```bash
--cookie .example.com:session=abc --cookie sso.example.com:token=xyz
```

Each cookie's own domain decides which requests carry it, so a separate auth subdomain
goes alongside the main one.

Or record the login once and replay it:

```bash
uv run qai <url> --login-url https://app/login --username u --password p \
  --login-success-indicator "/dashboard"
```

That prints a macro as JSON. Save it, then replay with `--login-macro path.json` on
later runs. `--login-success-indicator` is a URL substring or CSS selector proving the
login worked; without it a failed login looks like a successful scan of a login wall.

Auth is established **once**, before the run. There is no mid-crawl re-auth, so a
session that expires halfway leaves the rest of the crawl scanning logged-out pages.

## Scan an API from a spec

```bash
uv run qai https://api.example.com --spec ./openapi.json --spec-kind openapi
```

The positional URL becomes the base URL. `--spec-kind` is `openapi` (default) or
`graphql`. Operations are converted to the same field model the DOM fuzzer uses and
fired over HTTP — no browser DOM involved.

Via MCP, `qa_api_scan` takes the spec **text**, not a path.

## Optional checks

Three, opt-in, off by default: `idor`, `auth_bypass`, `security_headers`.

Available through the library and MCP (`plugins=["idor"]`), and they only actually fire
when `own_target=True` or the target is local — otherwise they report as skipped.

## Reading a finding

Fuzz intents: `valid`, `empty`, `boundary`, `overflow`, `malicious`, `unicode`,
`schema_violation`.

Finding kinds: `server_error`, `console_error`, `network_fail`, `invariant`,
`broken_link`, `dom_error`.

`dom_error` is the one a network-only checker misses — the request returned 200 and the
page rendered an error banner.

`source_location` is the `file:line` correlation. It resolves only when `--repo` pointed
at the code that actually serves the target.

## MCP tools

`qa_scan` · `qa_scan_html` · `qa_crawl` · `qa_api_scan` · `qa_login_record` ·
`qa_pipeline_start` · `qa_pipeline_step` · `qa_pipeline_report` · `qa_pipeline_abort`

The pipeline tools drive a scan step by step when you want to decide between stages
rather than fire one shot.

`qa_scan(screenshot=True)` and `qa_crawl(screenshot=True)` return paths you can `Read`
directly — that is how an agent sees the page it just scanned.

## Speed

The browser is the cost. `--parallel N` fans fuzz cases across N tabs. `--direct` does
one real UI submit per form to learn the request shape, then fires the rest straight
over HTTP — much faster, and it bypasses client-side `maxlength`/`type` constraints,
which is often what you want when hunting for missing server-side validation.

`--nav-timeout` (15s) and `--dom-stable-timeout` (4s) are wait budgets. Raise them for a
slow target or a heavy client-rendered page whose forms mount late; a too-short DOM
budget shows up as "no forms found" on a page that visibly has one.

## When something looks wrong

Zero findings on a remote host → check `safe_mode`; you probably never fuzzed.
No forms found → raise `--dom-stable-timeout`, the page likely mounts late.
No `file:line` → `--repo` missing or pointing at the wrong tree.
Crawl ended early → read `budget_exhausted_by` and `pages_not_visited`.
Everything behind a login wall → auth never applied, or it expired mid-run.
