from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "browser: needs a real Chromium (auto-applied, never write it by hand)"
    )


# Importing any of these is what actually launches Chromium — every one of them either
# is the browser wrapper or builds one internally.
_BROWSER_ENTRY_POINTS = frozenset(
    {"BrowserPool", "CaptureSession", "run_scan", "run_crawl", "run_api_scan"}
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Mark every test that needs a real Chromium as `browser`.

    Derived from what the test's module imports rather than written per-test: a
    hand-applied marker gets forgotten on the next browser test added, and that test
    then lands in the fast CI job where no browser exists — failing for a reason that
    has nothing to do with its subject.

    The demo_server fixture alone is not enough to detect this. Fifteen tests across
    six modules drive a browser directly without it, and keying only on the fixture
    left every one of them in the fast job.
    """
    for item in items:
        module = getattr(item, "module", None)
        needs_browser = "demo_server" in getattr(item, "fixturenames", ()) or any(
            hasattr(module, name) for name in _BROWSER_ENTRY_POINTS
        )
        if needs_browser:
            item.add_marker(pytest.mark.browser)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


@pytest.fixture(scope="session")
def demo_server() -> Iterator[str]:
    from qai.demo_target.app import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if server.started:
            break
        time.sleep(0.1)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)
