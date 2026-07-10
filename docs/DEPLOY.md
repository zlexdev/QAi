---
title: QAi — remote API deploy guide
---

# QAi — remote API deploy guide

This is the deep-dive companion to the README's
[Deploy — remote FastAPI service](../README.md#deploy--remote-fastapi-service)
section: every flag, every file `scripts/install.sh` touches, and the
troubleshooting steps for a shared/production host. Read the README section
first for the quickstart; come here for the details.

## What gets deployed

```
qai-api (uvicorn, single worker)
  ├─ /healthz              — unauthenticated liveness check
  ├─ /v1/scan|crawl|api-scan|login-record  — submit a job, 202 + job_id
  ├─ /v1/jobs/{id}         — poll job status/result
  ├─ /v1/pipeline/*        — mirrors qa_pipeline_* MCP tools, synchronous
  └─ /scalar               — interactive API reference (OpenAPI-driven)
```

Same engine the MCP server (`qai-mcp`) wraps (`qai.engine.runner.run_scan` /
`run_crawl`, `qai.engine.api_runner.run_api_scan`,
`qai.engine.auth.recorder.record_login`) — the API is a second transport, not
a second implementation. Long-running calls (scan/crawl/api-scan/login-record)
run as background jobs tracked in an **in-process** `JobStore`; pipeline
sessions are backed by the same `SqliteSessionStore` the MCP tools use, so a
session started on one transport can be driven from the other as long as they
point at the same `session_db_path`.

## Install phases (`scripts/install.sh`)

| Phase | What it does |
|---|---|
| 1/7 — system packages | `apt-get install curl nginx certbot python3-certbot-nginx`; installs `uv` if missing |
| 2/7 — python deps + browser | `uv sync --extra api --extra mcp`; `playwright install --with-deps chromium` |
| 3/7 — configuration | Prompts for a domain (skipped if cached), generates an API key (`openssl rand -hex 32` if not cached), writes `~/.qai.conf` and the app's `.env` |
| 4/7 — DNS check | `getent hosts $QAI_DOMAIN` must resolve — **fails loud and exits** if it doesn't; point an A/AAAA record at the host first |
| 5/7 — systemd unit | Renders `scripts/qai-api.service.template` → `/etc/systemd/system/qai-api.service`, `daemon-reload`, `enable` |
| 6/7 — nginx + TLS | Renders `scripts/nginx-qai.conf.template` → `/etc/nginx/sites-available/qai-api.conf`, symlinks into `sites-enabled`, `nginx -t`, `certbot --nginx -d $QAI_DOMAIN` |
| 7/7 — start + healthcheck | `systemctl restart qai-api`; `curl -fsS https://$QAI_DOMAIN/healthz` — fails the whole run if unreachable |

Idempotent: re-running after a `git pull` reuses the cached `~/.qai.conf`
(domain/port/API key/memory cap) and skips straight to syncing + restarting.
`bash scripts/install.sh --dry-run` prints every command it *would* run
(including the `sudo`/systemctl/nginx/certbot calls) without executing any of
them — use it to review the plan on an unfamiliar host first.

## Configuration reference

| Variable | Where | Default | What it does |
|---|---|---|---|
| `QAI_DOMAIN` | `~/.qai.conf`, prompted if unset | — | Public domain the nginx site + certbot cert bind to |
| `QAI_PORT` | `~/.qai.conf` | `8000` | Port `qai-api` (and nginx's upstream) listens on |
| `QAI_API_KEY` | `~/.qai.conf` + app `.env` | generated | Value every request must send as `X-API-Key` |
| `QAI_MEMORY_MAX` | env before running `install.sh`, cached after | `512M` | systemd `MemoryMax`/`MemorySwapMax=0` cap on `qai-api.service` |
| `QAI_HOST` | app `.env` only | `127.0.0.1` | uvicorn bind address — always loopback; nginx is the public front door |
| `QAI_SESSION_DB_PATH` | `qai.api.settings.Settings` | `qai-reports/.pipeline_sessions.sqlite3` | Same default path the MCP server's `_SESSION_STORE` uses |

`~/.qai.conf` is a flat `KEY=VALUE` file, safe to hand-edit before a re-run
(e.g. to rotate `QAI_API_KEY` — delete the line, re-run `install.sh`, it
regenerates and re-renders the `.env` + restarts the service).

## Operating it

```bash
systemctl status qai-api              # is it up, since when, last few log lines
journalctl -u qai-api -f              # follow logs live
systemctl restart qai-api             # after a manual .env edit
curl https://$QAI_DOMAIN/healthz      # liveness check (no auth)
```

Update to a new commit:

```bash
cd /path/to/QAi && git pull --ff-only
bash scripts/install.sh               # re-syncs deps, re-renders configs, restarts
```

## Shared-host memory (`QAI_MEMORY_MAX`)

A scan's Chromium process is the heaviest thing `qai-api` ever runs. On a box
that also runs other services, cap it so a stray heavy scan degrades only
`qai-api` — the systemd unit sets `MemoryMax=$QAI_MEMORY_MAX` and
`MemorySwapMax=0`, so the kernel OOM-kills the `qai-api` cgroup specifically
instead of picking a victim process host-wide:

```bash
QAI_MEMORY_MAX=768M bash scripts/install.sh
```

Guidance from a real deploy on a ~1.9 GB shared box (mail/chat/bot services
already resident): the default `512M` held for a single-page `qa_scan`
(peaked ~510 MiB) and a two-page `qa_crawl` (peaked right at the cap without
being killed). If jobs against your target need to hold more than one
concurrent tab or crawl multiple pages, raise the cap — but check the host's
own free memory (`free -h`) first; a cap larger than what the host can spare
just delays the same OOM further into a bigger job instead of preventing it.
Cap too low and legitimate scans fail with a generic connection-reset instead
of a job `error` — if that happens, check `journalctl -u qai-api` for an
OOM-kill line before assuming it's an application bug.

## Concurrency model — why single-worker

`JobStore` (in-process `dict`) and `PipelineRuntime` (in-process session/lock
maps) are **not shared across processes**. `qai-api`'s `main()` always calls
`uvicorn.run(..., workers=1)` — never override this with `--workers N` or a
process-manager fan-out, or jobs/sessions submitted to one worker become
invisible (404) to requests a load balancer routes to another. Scale
vertically (bigger box, higher `QAI_MEMORY_MAX`) or run independent instances
behind separate domains/ports, not multiple workers behind one.

## TLS / domain troubleshooting

- **`getent hosts $QAI_DOMAIN` fails at phase 4** — DNS hasn't propagated yet,
  or the A/AAAA record was never created. `dig +short $QAI_DOMAIN` from
  another machine to confirm; re-run `install.sh` once it resolves.
- **`certbot --nginx` fails** — needs port 80 reachable from the internet
  (firewall/security-group rule) and nginx already serving the plain-HTTP site
  for the ACME HTTP-01 challenge (phase 6 writes that before calling certbot).
- **`nginx -t` fails** — almost always a domain collision with an existing
  site on the same host; check `/etc/nginx/sites-enabled/` for another
  `server_name` claiming the same domain.
- **Renewal**: certbot's own systemd timer (`certbot.timer`, installed with
  the package) handles renewal — `install.sh` doesn't add a second one.

## Security notes

- `X-API-Key` is compared with `secrets.compare_digest` (constant-time) —
  never swap this for a plain `==` if you fork the auth dependency.
- The `.env` file `install.sh` writes is `chmod 600`; the systemd unit reads
  it via `EnvironmentFile=`, so the key never appears in `systemctl status`
  or process listings.
- Rotate `QAI_API_KEY` by editing `~/.qai.conf`, removing the old value, and
  re-running `install.sh` — it detects the missing key, generates a fresh
  one, and restarts the service with it.
- There is no rate limiting or multi-tenant auth built in — one shared key
  gates the whole service. Put it behind your own network ACLs/VPN if
  multiple untrusted parties could otherwise reach the domain.

## See also

- [README — Deploy: remote FastAPI service](../README.md#deploy--remote-fastapi-service) — quickstart + REST examples
- [README — Deploy: MCP](../README.md#deploy--install-as-a-plugin-for-ai-agents-mcp) — the other transport, same engine
- [USAGE.md](USAGE.md) — CLI/library/MCP reference
