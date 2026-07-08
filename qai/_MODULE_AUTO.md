# qai/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

> qai — autonomous form fuzzer that finds a bug and points at the line of code.

## Submodules

- [`demo_target/`](demo_target\_MODULE_AUTO.md) (1 py, 9 fn)
- [`engine/`](engine\_MODULE_AUTO.md) (36 py, 95 cls, 78 fn)

## cli.py
```
# qai CLI — `qai <url> --repo .` runs the full scan and prints/writes the report.

_LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}

_is_local_target(url: str) -> bool

_parse_cookie_arg(raw: str) -> CookieSpec

build_parser() -> argparse.ArgumentParser

async _load_login_macro(path: str) -> LoginMacro

async _record_and_print(args: argparse.Namespace, console: Console) -> int

main(argv: list[str]? = None) -> int

```

## mcp_server.py
```
# MCP server exposing the qai engine as tools for AI agents.

_LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}
_DEFAULT_PIPELINE_PLUGINS = ['security_headers']
_REAP_INTERVAL_SECONDS = 60.0
_SESSION_STORE = …

_lock_for(session_id: str) -> asyncio.Lock

async _reap_idle_pools_loop() -> None

async _lifespan(_server: FastMCP) -> AsyncIterator[None]

_resolve_safe_mode(url: str, own_target: bool) -> bool

_parse_cookies(raw: list[dict[str, str]]?) -> list[CookieSpec] | None

_parse_login_macro(raw: dict[str, object]?) -> LoginMacro | None

async qa_scan(url: str, repo_path: str? = None, headless: bool = True, parallel: int = 1, har_dir: str? = None, own_target: bool = False, direct_mode: bool = False, cookies: list[dict[str, str]]? = None, plugins: list[str]? = None, login_macro: dict[str, object]? = None, screenshot: bool = False, screenshot_dir: str? = None) -> str

async qa_scan_html(url: str, repo_path: str? = None, out_path: str = 'qai-report.html', headless: bool = True, parallel: int = 1, own_target: bool = False, login_macro: dict[str, object]? = None, screenshot: bool = False, screenshot_dir: str? = None) -> str

async qa_crawl(url: str, repo_path: str? = None, headless: bool = True, max_depth: int = 2, max_actions: int = 50, wall_clock_seconds: int = 180, allow_destructive: list[str]? = None, parallel: int = 1, own_target: bool = False, direct_mode: bool = False, cookies: list[dict[str, str]]? = None, login_macro: dict[str, object]? = None) -> str

async qa_api_scan(spec: str, base_url: str, spec_kind: str = 'openapi', repo_path: str? = None, headless: bool = True, own_target: bool = False, cookies: list[dict[str, str]]? = None, login_macro: dict[str, object]? = None, plugins: list[str]? = None) -> str

async qa_login_record(login_url: str, username: str, password: str, success_indicator: str? = None, own_target: bool = False, headless: bool = True) -> str

_build_stages(session: CaptureSession, plugin_names: list[str) -> list[Stage]

_plugin_names_from_steps(steps: list[StepInfo) -> list[str]

async _resume_pipeline(session_id: str) -> Pipeline

async _get_pipeline(session_id: str) -> Pipeline

async qa_pipeline_start(url: str, repo_path: str? = None, headless: bool = True, own_target: bool = False, cookies: list[dict[str, str]]? = None, plugins: list[str]? = None, login_macro: dict[str, object]? = None) -> str

async qa_pipeline_step(session_id: str, inject: dict[str, object]? = None, skip: bool = False, config: dict[str, object]? = None) -> str

_validate_step_config(pipeline: Pipeline, config: dict[str, object) -> None

async qa_pipeline_report(session_id: str) -> str

async qa_pipeline_abort(session_id: str) -> str
  # Close the session's live BrowserPool (if any) and delete its SQLite row.

main() -> None

```
