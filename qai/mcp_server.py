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
from pydantic import ValidationError

from qai.engine.contracts import CookieSpec, CrawlBudget
from qai.engine.errors import InvalidCookieSpecError, QaiError
from qai.engine.logging import configure_logging
from qai.engine.reporter import Reporter
from qai.engine.runner import run_crawl, run_scan

configure_logging()
mcp = FastMCP("qai")

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _resolve_safe_mode(url: str, own_target: bool) -> bool:
    return not (own_target or urlparse(url).hostname in _LOCAL_HOSTS)


def _parse_cookies(raw: list[dict[str, str]] | None) -> list[CookieSpec] | None:
    """Each dict needs ``name``/``value``/``domain`` (optional ``path``/``secure``/
    ``http_only``/``same_site``) — a separate auth/SSO subdomain's cookie can be listed
    alongside the main target's, since each carries its own ``domain``."""
    if not raw:
        return None
    try:
        return [CookieSpec(**c) for c in raw]
    except ValidationError as exc:
        raise InvalidCookieSpecError(str(raw), str(exc)) from exc


@mcp.tool()
async def qa_scan(
    url: str,
    repo_path: str | None = None,
    headless: bool = True,
    parallel: int = 1,
    har_dir: str | None = None,
    own_target: bool = False,
    direct_mode: bool = False,
    cookies: list[dict[str, str]] | None = None,
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
        cookies: auth cookies injected before any navigation, one dict per cookie with
            keys ``name``/``value``/``domain`` (optional ``path``/``secure``/
            ``http_only``/``same_site``) — lets the scan reach pages behind a login
            wall; a separate auth/SSO subdomain's cookie can be listed alongside the
            main target's since each carries its own domain.

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
            cookies=_parse_cookies(cookies),
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


@mcp.tool()
async def qa_crawl(
    url: str,
    repo_path: str | None = None,
    headless: bool = True,
    max_depth: int = 2,
    max_actions: int = 50,
    wall_clock_seconds: int = 180,
    allow_destructive: list[str] | None = None,
    parallel: int = 1,
    own_target: bool = False,
    direct_mode: bool = False,
    cookies: list[dict[str, str]] | None = None,
) -> str:
    """Discover same-origin pages (BFS, budgeted) from ``url`` and fuzz every form found.

    Links/buttons whose text matches a destructive keyword (delete/pay/withdraw/transfer/
    удалить/оплатить/... — see ``qai.engine.risk``) are never clicked unless their
    selector is in ``allow_destructive``. This is a heuristic, not a security guarantee —
    review the returned ``skipped_destructive`` list yourself.

    See ``qa_scan`` for the ``own_target``/safe-mode rule and the ``cookies`` shape —
    both apply identically here, per discovered page.

    Returns:
        JSON-encoded CrawlReport: run_id, root_url, states_visited, pages (one RunReport
        per page with a form), skipped_destructive, budget_exhausted_by, findings[].
    """
    safe_mode = _resolve_safe_mode(url, own_target)
    budget = CrawlBudget(
        max_depth=max_depth, max_actions=max_actions, wall_clock_seconds=wall_clock_seconds
    )
    try:
        report = await run_crawl(
            url,
            repo_path,
            headless=headless,
            budget=budget,
            allowlist=frozenset(allow_destructive or []),
            max_parallel=parallel,
            safe_mode=safe_mode,
            direct_mode=direct_mode,
            cookies=_parse_cookies(cookies),
        )
    except QaiError as exc:
        return json.dumps({"error": str(exc), "error_type": type(exc).__name__})
    return report.model_dump_json()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
