"""qai CLI — `qai <url> --repo .` runs the full scan and prints/writes the report."""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path
from urllib.parse import urlparse

from rich.console import Console

from qai.engine.contracts import CrawlBudget, ScanReport
from qai.engine.errors import QaiError
from qai.engine.logging import configure_logging
from qai.engine.reporter import Reporter
from qai.engine.runner import run_crawl, run_scan

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _is_local_target(url: str) -> bool:
    return urlparse(url).hostname in _LOCAL_HOSTS


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
        "--wall-clock", type=int, default=180, help="Crawl: overall time budget in seconds"
    )
    parser.add_argument(
        "--allow-destructive",
        action="append",
        default=[],
        metavar="SELECTOR",
        help="Selector explicitly allowed to be clicked despite looking destructive "
        "(repeatable). Review qai's destructive keyword heuristic before using this.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    # Classic Windows terminals default stdout to cp1252, which raises on the report's
    # unicode glyphs (severity dot); force UTF-8 so the report never crashes on render.
    for stream in (sys.stdout, sys.stderr):
        if isinstance(stream, io.TextIOWrapper) and stream.encoding.lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")

    args = build_parser().parse_args(argv)
    configure_logging(level=10 if args.verbose else 20)
    console = Console(legacy_windows=False)

    safe_mode = not (args.own_target or _is_local_target(args.url))
    if safe_mode:
        console.print(
            "[dim]Non-local target without --i-own-this-target: modeling the page only, "
            "no field will be filled or submitted.[/dim]"
        )

    report: ScanReport
    try:
        if args.crawl:
            budget = CrawlBudget(
                max_depth=args.max_depth,
                max_actions=args.max_actions,
                wall_clock_seconds=args.wall_clock,
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
        reporter.write_json(report, json_path)
        reporter.write_markdown(report, md_path)
        console.print(f"[dim]Report saved: {json_path}, {md_path}[/dim]")

    return 0 if report.ok else 2


if __name__ == "__main__":
    sys.exit(main())
