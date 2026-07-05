"""MCP server exposing the qai engine as tools for AI agents.

This is the SaaS-boundary CUT#6 stand-in for the MVP: the same engine, the same
``Finding[]``/``RunReport`` contract, wrapped as MCP tools instead of a REST facade.
The engine never imports this module — the boundary invariant holds both ways.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP

from qai.engine.errors import QaiError
from qai.engine.logging import configure_logging
from qai.engine.reporter import Reporter
from qai.engine.runner import run_scan

configure_logging()
mcp = FastMCP("qai")

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _resolve_safe_mode(url: str, own_target: bool) -> bool:
    return not (own_target or urlparse(url).hostname in _LOCAL_HOSTS)


@mcp.tool()
async def qa_scan(
    url: str,
    repo_path: str | None = None,
    headless: bool = True,
    parallel: int = 1,
    har_dir: str | None = None,
    own_target: bool = False,
    direct_mode: bool = False,
) -> str:
    """Run the full qai pipeline against ``url`` and return a JSON RunReport.

    Args:
        url: Target URL to scan.
        repo_path: Optional path to the target's source repo — enables file:line
            correlation of findings back to the FastAPI handler that produced them.
        headless: Run the browser headless (default) or headed for debugging.
        parallel: Number of concurrent tabs to fan fuzz cases across (each tagged
            ``tab_id`` in the returned findings, for log/request correlation).
        har_dir: If set, records a ``.har`` per tab under this directory.
        own_target: Must be True to actually submit fuzz payloads against a non-local
            host — without it, a non-local URL is only page-modeled (no fill/submit),
            so an agent can never accidentally fuzz a production site it doesn't own.
        direct_mode: after one baseline UI submit per form, fuzz the rest straight over
            HTTP (faster, bypasses client-side maxlength/type constraints); falls back
            to the UI path per-form when the baseline body isn't a simple shape.

    Returns:
        JSON-encoded RunReport: run_id, forms_scanned, cases_executed, tabs_used,
        safe_mode, findings[]. Each finding carries severity, kind, detail, tab_id,
        and (if repo_path was given) source_location.file/line pointing at the handler.
    """
    safe_mode = _resolve_safe_mode(url, own_target)
    try:
        report = await run_scan(
            url,
            repo_path,
            headless=headless,
            max_parallel=parallel,
            har_dir=har_dir,
            safe_mode=safe_mode,
            direct_mode=direct_mode,
        )
    except QaiError as exc:
        return json.dumps({"error": str(exc), "error_type": type(exc).__name__})
    return report.model_dump_json()


@mcp.tool()
async def qa_scan_html(
    url: str,
    repo_path: str | None = None,
    out_path: str = "qai-report.html",
    headless: bool = True,
    parallel: int = 1,
    own_target: bool = False,
) -> str:
    """Run a scan and write a self-contained dark-themed HTML report to ``out_path``.

    Use this when a human will read the result — the HTML report is the polished
    surface (clickable file:line, severity-colored rows). Returns the JSON summary
    plus the written path. See ``qa_scan`` for the ``own_target``/safe-mode rule.
    """
    safe_mode = _resolve_safe_mode(url, own_target)
    try:
        report = await run_scan(
            url, repo_path, headless=headless, max_parallel=parallel, safe_mode=safe_mode
        )
    except QaiError as exc:
        return json.dumps({"error": str(exc), "error_type": type(exc).__name__})
    path = Path(out_path)
    Reporter().write_html(report, path)
    return json.dumps(
        {
            "run_id": report.run_id,
            "ok": report.ok,
            "safe_mode": report.safe_mode,
            "findings_count": len(report.findings),
            "html_report": str(path.resolve()),
        }
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
