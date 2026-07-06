# qai/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

> qai — autonomous form fuzzer that finds a bug and points at the line of code.

## Submodules

- [`demo_target/`](demo_target\_MODULE_AUTO.md) (1 py, 2 fn)
- [`engine/`](engine\_MODULE_AUTO.md) (16 py, 56 cls, 39 fn)

## cli.py
```
# qai CLI — `qai <url> --repo .` runs the full scan and prints/writes the report.

_LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}

_is_local_target(url: str) -> bool

build_parser() -> argparse.ArgumentParser

main(argv: list[str]? = None) -> int

```

## mcp_server.py
```
# MCP server exposing the qai engine as tools for AI agents.

_LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1'}

_resolve_safe_mode(url: str, own_target: bool) -> bool

async qa_scan(url: str, repo_path: str? = None, headless: bool = True, parallel: int = 1, har_dir: str? = None, own_target: bool = False, direct_mode: bool = False) -> str

async qa_scan_html(url: str, repo_path: str? = None, out_path: str = 'qai-report.html', headless: bool = True, parallel: int = 1, own_target: bool = False) -> str

async qa_crawl(url: str, repo_path: str? = None, headless: bool = True, max_depth: int = 2, max_actions: int = 50, wall_clock_seconds: int = 180, allow_destructive: list[str]? = None, parallel: int = 1, own_target: bool = False, direct_mode: bool = False) -> str

main() -> None

```
