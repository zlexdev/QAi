"""Reporter — the showcase surface. Terminal rich table + a self-contained dark HTML report.

Per PLAN: this is where the polish budget goes — the report is what earns "works / doesn't",
not the engine internals. JSON is the machine surface for CI.
"""

from __future__ import annotations

import html
from pathlib import Path

from rich.console import Console
from rich.table import Table

from qai.engine.contracts import Finding, RunReport, Severity


def _severity_key(finding: Finding) -> int:
    return _SEVERITY_ORDER[finding.severity]


_SEVERITY_STYLE = {
    Severity.HIGH: "bold red",
    Severity.MEDIUM: "bold yellow",
    Severity.LOW: "dim cyan",
}
_SEVERITY_DOT = {Severity.HIGH: "●", Severity.MEDIUM: "●", Severity.LOW: "●"}


class Reporter:
    def print_table(self, report: RunReport, console: Console | None = None) -> None:
        console = console or Console(legacy_windows=False)
        table = Table(title=f"qai run {report.run_id} — {report.target_url}")
        table.add_column("Sev")
        table.add_column("Kind")
        table.add_column("Field")
        table.add_column("Intent")
        table.add_column("Detail", overflow="fold")
        table.add_column("Source")

        for f in sorted(report.findings, key=_severity_key):
            style = _SEVERITY_STYLE[f.severity]
            source = (
                f"{f.source_location.file}:{f.source_location.line}" if f.source_location else "-"
            )
            table.add_row(
                f"[{style}]{_SEVERITY_DOT[f.severity]} {f.severity.value}[/{style}]",
                f.kind.value,
                f.field_selector or "-",
                f.intent.value if f.intent else "-",
                f.detail,
                source,
            )

        console.print(table)
        summary = (
            f"forms={report.forms_scanned} cases={report.cases_executed} "
            f"findings={len(report.findings)}"
        )
        style = "bold green" if report.ok else "bold red"
        console.print(f"[{style}]{summary}[/{style}]")

    def write_json(self, report: RunReport, path: Path) -> None:
        path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    def write_html(self, report: RunReport, path: Path) -> None:
        path.write_text(_render_html(report), encoding="utf-8")


_SEVERITY_ORDER = {Severity.HIGH: 0, Severity.MEDIUM: 1, Severity.LOW: 2}
_SEVERITY_COLOR = {Severity.HIGH: "#f85149", Severity.MEDIUM: "#d29922", Severity.LOW: "#58a6ff"}


def _render_html(report: RunReport) -> str:
    ordered = sorted(report.findings, key=_severity_key)
    rows = "\n".join(_finding_row(f) for f in ordered)
    status = "PASS" if report.ok else "FAIL"
    status_color = "#3fb950" if report.ok else "#f85149"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>qai report {html.escape(report.run_id)}</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #0a0a0b; color: #e8e8e8;
    font: 14px/1.5 -apple-system, "Segoe UI", Inter, sans-serif;
    padding: 40px 48px;
  }}
  header {{ margin-bottom: 32px; }}
  h1 {{ font-size: 22px; font-weight: 600; letter-spacing: -0.02em; margin-bottom: 6px; }}
  .meta {{ color: #8b8b8f; font-size: 13px; }}
  .status {{
    display: inline-block; margin-top: 14px; padding: 4px 12px; border-radius: 20px;
    font-size: 12px; font-weight: 600; letter-spacing: 0.02em;
    background: {status_color}22; color: {status_color}; border: 1px solid {status_color}55;
  }}
  table {{ width: 100%; border-collapse: collapse; margin-top: 24px; }}
  th {{
    text-align: left; font-size: 11px; text-transform: none; color: #8b8b8f;
    font-weight: 500; padding: 10px 14px; border-bottom: 1px solid rgba(255,255,255,.08);
  }}
  td {{
    padding: 12px 14px; border-bottom: 1px solid rgba(255,255,255,.06);
    vertical-align: top; font-size: 13px;
  }}
  tr:hover td {{ background: rgba(255,255,255,.03); }}
  .sev {{ font-weight: 600; white-space: nowrap; }}
  .sev::before {{ content: "●"; margin-right: 6px; }}
  .detail {{ color: #c9c9cc; max-width: 480px; }}
  code {{ font-family: ui-monospace, "SF Mono", Consolas, monospace; font-size: 12.5px; }}
  a.loc {{ color: #58a6ff; text-decoration: none; }}
  a.loc:hover {{ text-decoration: underline; }}
  .empty {{ color: #8b8b8f; padding: 40px 0; text-align: center; }}
</style>
</head>
<body>
<header>
  <h1>qai scan report</h1>
  <div class="meta">run <code>{html.escape(report.run_id)}</code> &middot;
    target <code>{html.escape(report.target_url)}</code> &middot;
    forms={report.forms_scanned} cases={report.cases_executed}</div>
  <span class="status">{status}</span>
</header>
{_table_or_empty(report, rows)}
</body>
</html>"""


def _table_or_empty(report: RunReport, rows: str) -> str:
    if not report.findings:
        return '<div class="empty">No findings — every case behaved as expected.</div>'
    return f"""<table>
  <thead><tr><th>Severity</th><th>Kind</th><th>Field</th><th>Intent</th><th>Detail</th><th>Source</th></tr></thead>
  <tbody>
{rows}
  </tbody>
</table>"""


def _finding_row(f: Finding) -> str:
    color = _SEVERITY_COLOR[f.severity]
    source = "-"
    if f.source_location:
        loc = f"{html.escape(f.source_location.file)}:{f.source_location.line}"
        source = f'<a class="loc" href="#"><code>{loc}</code></a>'
    return f"""    <tr>
      <td class="sev" style="color:{color}">{f.severity.value}</td>
      <td>{html.escape(f.kind.value)}</td>
      <td><code>{html.escape(f.field_selector or "-")}</code></td>
      <td>{html.escape(f.intent.value if f.intent else "-")}</td>
      <td class="detail">{html.escape(f.detail)}</td>
      <td>{source}</td>
    </tr>"""
