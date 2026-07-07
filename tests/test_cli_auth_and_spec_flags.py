"""CLI: --login-url record-only mode, --login-macro replay, --spec API-scan mode —
and a backward-compat check that none of the existing scan/crawl flags changed
behavior when the new flags are omitted."""

from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

from qai.cli import build_parser, main

_SPEC_PATH = Path(__file__).resolve().parents[1] / "qai" / "demo_target" / "openapi.json"


def test_parser_accepts_spec_and_login_flags() -> None:
    parser = build_parser()
    ns = parser.parse_args(
        ["http://localhost:8000", "--spec", "spec.json", "--spec-kind", "openapi"]
    )
    assert ns.spec == "spec.json"
    assert ns.spec_kind == "openapi"

    ns2 = parser.parse_args(
        [
            "unused",
            "--login-url",
            "http://localhost:8000/login",
            "--username",
            "admin",
            "--password",
            "secret",
        ]
    )
    assert ns2.login_url == "http://localhost:8000/login"
    assert ns2.username == "admin"
    assert ns2.password == "secret"

    ns3 = parser.parse_args(["http://localhost:8000", "--login-macro", "macro.json"])
    assert ns3.login_macro == "macro.json"


def test_login_url_record_mode_prints_macro_json(demo_server: str) -> None:
    # contextlib.redirect_stdout (not pytest's capsys) — capsys also swaps sys.stderr,
    # and main() -> configure_logging() binds structlog's global PrintLoggerFactory to
    # whatever sys.stderr is AT THAT MOMENT (cache_logger_on_first_use=True); capsys
    # closes its captured buffer at teardown, which would leave structlog holding a
    # closed file handle for every later test in the session ("I/O operation on closed
    # file"). redirect_stdout leaves sys.stderr untouched, so this can't happen.
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        exit_code = main(
            [
                "unused",
                "--login-url",
                f"{demo_server}/login",
                "--username",
                "admin",
                "--password",
                "secret",
                "--i-own-this-target",
            ]
        )
    assert exit_code == 0
    payload = json.loads(buffer.getvalue())
    assert payload["auth_result"]["authenticated"] is True


def test_spec_flag_runs_api_scan(demo_server: str, tmp_path: Path) -> None:
    spec_path = tmp_path / "openapi.json"
    spec_path.write_text(_SPEC_PATH.read_text())
    exit_code = main([demo_server, "--spec", str(spec_path), "--i-own-this-target", "--no-auto-report"])
    assert exit_code in (0, 2)  # 2 = findings present, both are a successful run


def test_scan_without_new_flags_is_unaffected(demo_server: str) -> None:
    """Regression guard: existing scan flags behave identically when none of the new
    flags are passed — same exit-code contract as before this plan."""
    exit_code = main([demo_server, "--i-own-this-target", "--no-auto-report"])
    assert exit_code in (0, 2)
