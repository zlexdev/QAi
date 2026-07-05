"""CodeCorrelator — resolves a captured request to file:line in the target repo.

Self-contained by default (per rule: prefer no external CLI dependency when stdlib
suffices): route table is built with Python's own ``ast`` module against FastAPI
decorator syntax (``@router.get("/x")`` / ``@app.post("/x")``), no ast-grep binary
required. If the ``cx`` CLI (codeanalyzer) is on PATH, its call-graph is used to enrich
the finding with callees/field-writes; without it we degrade gracefully to the bare
handler location — this never blocks Phase 3.
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from qai.engine.contracts import CapturedRequest, HttpMethod, SourceRef
from qai.engine.errors import RouteResolveError
from qai.engine.logging import get_logger

_log = get_logger("correlator")

_ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}
_PARAM_RE = re.compile(r"\{[^{}]+\}")


@dataclass(frozen=True, slots=True)
class RouteEntry:
    method: HttpMethod
    template: str
    file: str
    line: int
    handler_symbol: str


class RouteTable:
    """route_template + method -> RouteEntry, built once per repo (incremental later)."""

    def __init__(self, entries: list[RouteEntry]) -> None:
        self._entries = entries
        # Longest-template-first so /users/{id}/orders wins over /users/{id}.
        self._by_method: dict[HttpMethod, list[RouteEntry]] = {}
        for e in sorted(entries, key=lambda x: -len(x.template)):
            self._by_method.setdefault(e.method, []).append(e)

    def resolve(self, method: HttpMethod, path: str) -> RouteEntry | None:
        for entry in self._by_method.get(method, []):
            if _match(entry.template, path):
                return entry
        return None

    def __len__(self) -> int:
        return len(self._entries)


def build_route_table(repo_path: Path) -> RouteTable:
    """Scan every ``*.py`` file under ``repo_path`` for FastAPI route decorators."""
    entries: list[RouteEntry] = []
    for file in repo_path.rglob("*.py"):
        if any(part in {".venv", "venv", ".git", "node_modules"} for part in file.parts):
            continue
        entries += _scan_file(file, repo_path)
    _log.info("route_table_built", routes=len(entries))
    return RouteTable(entries)


def _scan_file(file: Path, repo_root: Path) -> list[RouteEntry]:
    try:
        source = file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file))
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        _log.warning("route_scan_skip", file=str(file), error=str(exc))
        return []

    out: list[RouteEntry] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        for deco in node.decorator_list:
            hit = _match_route_decorator(deco)
            if hit is None:
                continue
            method, template = hit
            out.append(
                RouteEntry(
                    method=method,
                    template=template,
                    file=str(file.relative_to(repo_root)),
                    line=node.lineno,
                    handler_symbol=node.name,
                )
            )
    return out


def _match_route_decorator(deco: ast.expr) -> tuple[HttpMethod, str] | None:
    if not isinstance(deco, ast.Call) or not isinstance(deco.func, ast.Attribute):
        return None
    attr = deco.func.attr.lower()
    if attr not in _ROUTE_METHODS:
        return None
    if not deco.args or not isinstance(deco.args[0], ast.Constant):
        return None
    path = deco.args[0].value
    if not isinstance(path, str):
        return None
    try:
        method = HttpMethod(attr.upper())
    except ValueError:
        return None
    return method, path


def _match(template: str, path: str) -> bool:
    # Escape literal segments only; re.escape would also escape the {param} braces
    # themselves, so split on them first and re-join with the wildcard.
    parts = _PARAM_RE.split(template)
    pattern = "^" + "[^/]+".join(re.escape(p) for p in parts) + "$"
    return re.match(pattern, path) is not None


class CodeCorrelator:
    """Resolves CapturedRequest -> SourceRef using the route table + optional cx."""

    def __init__(self, route_table: RouteTable, repo_path: Path) -> None:
        self._routes = route_table
        self._repo_path = repo_path
        self._cx_available = shutil.which("cx") is not None

    def correlate(self, request: CapturedRequest) -> SourceRef | None:
        path = urlparse(request.url).path
        entry = self._routes.resolve(request.method, path)
        if entry is None:
            _log.info("route_unresolved", method=request.method.value, path=path)
            return None
        callees, field_writes = self._enrich_via_cx(entry.handler_symbol)
        return SourceRef(
            file=entry.file,
            line=entry.line,
            symbol=entry.handler_symbol,
            callees=callees,
            field_writes=field_writes,
        )

    def _enrich_via_cx(self, symbol: str) -> tuple[list[str], list[str]]:
        if not self._cx_available:
            return [], []
        try:
            proc = subprocess.run(
                ["cx", "query", symbol, "--raw"],
                cwd=self._repo_path,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            _log.warning("cx_query_failed", symbol=symbol, error=str(exc))
            return [], []
        if proc.returncode != 0:
            return [], []
        return _parse_cx_output(proc.stdout)


def _parse_cx_output(raw: str) -> tuple[list[str], list[str]]:
    """Best-effort line-based parse of ``cx query --raw`` text output."""
    callees: list[str] = []
    writes: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("calls:") or stripped.startswith("calls "):
            callees.append(stripped.split(":", 1)[-1].strip())
        elif stripped.startswith("writes:") or stripped.startswith("field_write"):
            writes.append(stripped.split(":", 1)[-1].strip())
    return callees, writes


def require_repo(repo_path: Path) -> Path:
    if not repo_path.is_dir():
        raise RouteResolveError(route=None, cause=f"repo path not found: {repo_path}")
    return repo_path
