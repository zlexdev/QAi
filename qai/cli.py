"""qai CLI — `qai <url> --repo .` runs the full scan and prints/writes the report."""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path
from urllib.parse import urlparse

from rich.console import Console

from qai.engine.api_runner import run_api_scan
from qai.engine.apispec.contracts import ApiSpecKind, ApiSpecSource
from qai.engine.auth.contracts import LoginMacro
from qai.engine.auth.recorder import record_login
from qai.engine.capture import BrowserPool
from qai.engine.contracts import CookieSpec, CrawlBudget, ScanReport, TimeoutConfig
from qai.engine.errors import InvalidCookieSpecError, QaiError
from qai.engine.logging import configure_logging
from qai.engine.reporter import Reporter
from qai.engine.runner import run_crawl, run_scan

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_local_target(url: str) -> bool:
    return urlparse(url).hostname in _LOCAL_HOSTS


def _parse_cookie_arg(raw: str) -> CookieSpec:
    """Parse ``domain:name=value`` — e.g. ``.funpay.com:golden_key=abc123``, repeatable
    so cookies for a separate auth/SSO subdomain can be supplied alongside the main
    target's own."""
    domain, sep, rest = raw.partition(":")
    if not sep:
        raise InvalidCookieSpecError(raw, "missing ':' — expected domain:name=value")
    name, sep, value = rest.partition("=")
    if not sep:
        raise InvalidCookieSpecError(raw, "missing '=' — expected domain:name=value")
    if not domain or not name:
        raise InvalidCookieSpecError(raw, "domain and name must be non-empty")
    return CookieSpec(name=name, value=value, domain=domain)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qai",
        description="Autonomous form fuzzer: URL -> fuzz -> file:line of the bug.",
    )
    parser.add_argument("url", help="Target URL to scan (staging only — see README)")
    parser.add_argument("--repo", default=None, help="Path to the target's source repo")
    parser.add_argument("--json", dest="json_out", default=None, help="Write JSON report here")
    parser.add_argument("--html", dest="html_out", default=None, help="Write HTML report here")
    parser.add_argument(
        "--report-dir",
        default="qai-reports",
        help="Auto-generated .json + .md report directory (default: ./qai-reports)",
    )
    parser.add_argument(
        "--no-auto-report",
        dest="auto_report",
        action="store_false",
        help="Disable the automatic .json/.md report written to --report-dir on every run",
    )
    parser.add_argument("--headed", action="store_true", help="Run the browser headed")
    parser.add_argument("--verbose", action="store_true", help="Debug-level logging")
    parser.add_argument(
        "--parallel",
        type=int,
        default=1,
        metavar="N",
        help="Run fuzz cases across N concurrent tabs (each tagged tab-<i> in findings)",
    )
    parser.add_argument("--har", dest="har_dir", default=None, help="Record a .har per tab into this dir")
    parser.add_argument(
        "--direct",
        dest="direct_mode",
        action="store_true",
        help="After one baseline UI submit per form, fuzz the rest straight over HTTP "
        "(faster, bypasses client-side maxlength/type constraints)",
    )
    parser.add_argument(
        "--i-own-this-target",
        dest="own_target",
        action="store_true",
        help="Required to actually submit fuzz payloads — without it, qai only models "
        "the page (no fill/submit) so an accidental scan of a site you don't control "
        "never sends anything.",
    )
    parser.add_argument(
        "--crawl",
        action="store_true",
        help="Discover same-origin pages (BFS, budgeted) and fuzz every form found, "
        "instead of just the given URL. Destructive-looking links/buttons are never "
        "clicked by default — see --allow-destructive.",
    )
    parser.add_argument("--max-depth", type=int, default=2, help="Crawl: max BFS depth")
    parser.add_argument(
        "--max-actions", type=int, default=50, help="Crawl: max links/buttons followed"
    )
    parser.add_argument(
        "--wall-clock", type=int, default=300, help="Crawl: overall time budget in seconds"
    )
    parser.add_argument(
        "--no-subdomains",
        action="store_true",
        help="Crawl: only follow the exact root host, not its subdomains",
    )
    parser.add_argument(
        "--nav-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Override the page-navigation wait budget (default 15s) — raise it for a "
        "target that's legitimately slow to respond",
    )
    parser.add_argument(
        "--dom-stable-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Override the post-load DOM-settle wait budget (default 4s) — raise it for "
        "a heavy client-rendered page whose forms/buttons take longer to mount",
    )
    parser.add_argument(
        "--allowed-domain",
        dest="allowed_domains",
        action="append",
        default=[],
        metavar="HOST",
        help="Crawl: extra host allowed alongside the root (repeatable) — e.g. a "
        "separate auth/SSO or API subdomain that isn't a subdomain of the root",
    )
    parser.add_argument(
        "--allow-destructive",
        action="append",
        default=[],
        metavar="SELECTOR",
        help="Selector explicitly allowed to be clicked despite looking destructive "
        "(repeatable). Review qai's destructive keyword heuristic before using this.",
    )
    parser.add_argument(
        "--cookie",
        dest="cookies",
        action="append",
        default=[],
        metavar="DOMAIN:NAME=VALUE",
        help="Inject an auth cookie before any navigation (repeatable). Each cookie's "
        "own domain decides which requests carry it, so a separate auth/SSO subdomain "
        "can be supplied alongside the main target's, e.g. "
        "--cookie .example.com:session=abc --cookie sso.example.com:token=xyz",
    )
    parser.add_argument(
        "--spec", default=None, help="Path to an OpenAPI/GraphQL spec file — switches to "
        "API-scan mode (positional url becomes the API's base_url)"
    )
    parser.add_argument(
        "--spec-kind", default="openapi", choices=["openapi", "graphql"],
        help="Kind of --spec file (default: openapi)"
    )
    parser.add_argument("--login-url", default=None, help="Login page URL — record a login")
    parser.add_argument("--username", default=None, help="Username for --login-url")
    parser.add_argument("--password", default=None, help="Password for --login-url")
    parser.add_argument(
        "--login-success-indicator", default=None,
        help="URL substring or CSS selector proving --login-url succeeded"
    )
    parser.add_argument(
        "--login-macro", default=None, metavar="PATH",
        help="Load a previously-recorded LoginMacro JSON file and replay it before the scan/crawl"
    )
    parser.add_argument(
        "--screenshot", action="store_true",
        help="Save a PNG of the recon page; path is printed and included in --json output"
    )
    parser.add_argument(
        "--screenshot-dir", default=None, metavar="DIR",
        help="Directory the screenshot is saved under (default: qai-reports/screenshots)"
    )
    return parser


async def _load_login_macro(path: str) -> LoginMacro:
    return LoginMacro.model_validate_json(Path(path).read_text())


async def _record_and_print(args: argparse.Namespace, console: Console) -> int:
    if not (args.own_target or _is_local_target(args.login_url)):
        console.print(
            "[bold red]qai error:[/bold red] --i-own-this-target required to record a "
            "login against a non-local target"
        )
        return 1
    pool = await BrowserPool.create(headless=not args.headed)
    try:
        macro, auth_result = await record_login(
            pool,
            args.login_url,
            args.username,
            args.password,
            success_indicator=args.login_success_indicator,
        )
    finally:
        await pool.close()
    console.print_json(
        data={
            "macro": macro.model_dump(mode="json"),
            "auth_result": auth_result.model_dump(mode="json"),
        }
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    # Classic Windows terminals default stdout to cp1252, which raises on the report's
    # unicode glyphs (severity dot); force UTF-8 so the report never crashes on render.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    configure_logging(level=10 if args.verbose else 20)
    console = Console(legacy_windows=False)

    # --login-url alone (no --spec) is "record only, print macro JSON, exit" mode —
    # the required positional `url` is simply unused in this mode.
    if args.login_url:
        try:
            return asyncio.run(_record_and_print(args, console))
        except QaiError as exc:
            console.print(f"[bold red]qai error:[/bold red] {exc}")
            return 1

    safe_mode = not (args.own_target or _is_local_target(args.url))
    if safe_mode:
        console.print(
            "[dim]Non-local target without --i-own-this-target: modeling the page only, "
            "no field will be filled or submitted.[/dim]"
        )

    report: ScanReport
    try:
        cookies = [_parse_cookie_arg(raw) for raw in args.cookies]
        login_macro = asyncio.run(_load_login_macro(args.login_macro)) if args.login_macro else None
        timeout_overrides: dict[str, int] = {}
        if args.nav_timeout is not None:
            timeout_overrides["nav_ms"] = int(args.nav_timeout * 1000)
        if args.dom_stable_timeout is not None:
            timeout_overrides["dom_stable_ms"] = int(args.dom_stable_timeout * 1000)
        timeouts = TimeoutConfig(**timeout_overrides) if timeout_overrides else None

        if args.spec:
            spec_source = ApiSpecSource(
                kind=ApiSpecKind(args.spec_kind), raw=Path(args.spec).read_text()
            )
            report = asyncio.run(
                run_api_scan(
                    spec_source,
                    args.url,
                    args.repo,
                    headless=not args.headed,
                    safe_mode=safe_mode,
                    cookies=cookies,
                    login_macro=login_macro,
                )
            )
        elif args.crawl:
            budget = CrawlBudget(
                max_depth=args.max_depth,
                max_actions=args.max_actions,
                wall_clock_seconds=args.wall_clock,
                include_subdomains=not args.no_subdomains,
                allowed_domains=args.allowed_domains,
            )
            report = asyncio.run(
                run_crawl(
                    args.url,
                    args.repo,
                    headless=not args.headed,
                    budget=budget,
                    allowlist=frozenset(args.allow_destructive),
                    max_parallel=args.parallel,
                    har_dir=args.har_dir,
                    safe_mode=safe_mode,
                    direct_mode=args.direct_mode,
                    cookies=cookies,
                    login_macro=login_macro,
                    timeouts=timeouts,
                )
            )
        else:
            report = asyncio.run(
                run_scan(
                    args.url,
                    args.repo,
                    headless=not args.headed,
                    max_parallel=args.parallel,
                    har_dir=args.har_dir,
                    safe_mode=safe_mode,
                    direct_mode=args.direct_mode,
                    cookies=cookies,
                    login_macro=login_macro,
                    screenshot=args.screenshot,
                    screenshot_dir=args.screenshot_dir,
                    timeouts=timeouts,
                )
            )
    except QaiError as exc:
        console.print(f"[bold red]qai error:[/bold red] {exc}")
        return 1

    if args.crawl:
        skipped = getattr(report, "skipped_destructive", [])
        if skipped:
            console.print(
                f"[yellow]Skipped {len(skipped)} destructive-looking action(s) — "
                "see --allow-destructive[/yellow]"
            )
        exhausted = getattr(report, "budget_exhausted_by", None)
        if exhausted:
            console.print(f"[dim]Crawl stopped early: budget exhausted ({exhausted})[/dim]")

    screenshot_path = getattr(report, "screenshot_path", None)
    if screenshot_path:
        console.print(f"[dim]Screenshot saved: {screenshot_path}[/dim]")

    reporter = Reporter()
    reporter.print_table(report, console)
    if args.json_out:
        reporter.write_json(report, Path(args.json_out))
        console.print(f"[dim]JSON written to {args.json_out}[/dim]")
    if args.html_out:
        reporter.write_html(report, Path(args.html_out))
        console.print(f"[dim]HTML written to {args.html_out}[/dim]")

    if args.auto_report:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        json_path = report_dir / f"{report.run_id}.json"
        md_path = report_dir / f"{report.run_id}.md"
        findings_path = report_dir / f"{report.run_id}.findings.json"
        reporter.write_json(report, json_path)
        reporter.write_markdown(report, md_path)
        reporter.write_findings(report, findings_path)
        console.print(f"[dim]Report saved: {json_path}, {md_path}, {findings_path}[/dim]")

    return 0 if report.ok else 2


if __name__ == "__main__":
    sys.exit(main())
