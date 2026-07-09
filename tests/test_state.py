from __future__ import annotations

import pytest

from qai.engine.capture import CaptureSession
from qai.engine.state import compute_state, is_in_scope, is_in_scope_any, normalize_url


def test_normalize_url_strips_fragment_and_trailing_slash() -> None:
    assert normalize_url("http://x/a/#section") == normalize_url("http://x/a")


def test_is_in_scope_exact_host_always_allowed() -> None:
    assert is_in_scope("https://example.com/a", "example.com", include_subdomains=False)


def test_is_in_scope_rejects_other_domain() -> None:
    assert not is_in_scope("https://evil.com/a", "example.com", include_subdomains=True)


def test_is_in_scope_subdomain_only_allowed_when_enabled() -> None:
    assert is_in_scope("https://shop.example.com/a", "example.com", include_subdomains=True)
    assert not is_in_scope("https://shop.example.com/a", "example.com", include_subdomains=False)


def test_is_in_scope_rejects_lookalike_suffix_domain() -> None:
    # "notexample.com" ends with "example.com" as a raw string but is not a subdomain of it.
    assert not is_in_scope("https://notexample.com/a", "example.com", include_subdomains=True)


def test_is_in_scope_any_allows_extra_domain_not_a_subdomain_of_root() -> None:
    hosts = ["example.com", "auth.other.com"]
    assert is_in_scope_any("https://auth.other.com/login", hosts, include_subdomains=False)
    assert not is_in_scope_any("https://unrelated.com/x", hosts, include_subdomains=False)


@pytest.mark.asyncio
async def test_same_structure_different_text_yields_same_hash() -> None:
    async with CaptureSession(headless=True, run_id="t") as session:
        await session.page.set_content("<body><div><p>Hello</p></div></body>")
        a = await compute_state(session.page)
        await session.page.set_content("<body><div><p>Goodbye world</p></div></body>")
        b = await compute_state(session.page)
    assert a.dom_hash == b.dom_hash


@pytest.mark.asyncio
async def test_different_structure_yields_different_hash() -> None:
    async with CaptureSession(headless=True, run_id="t") as session:
        await session.page.set_content("<body><div><p>Hello</p></div></body>")
        a = await compute_state(session.page)
        await session.page.set_content("<body><div><p>Hello</p><span>x</span></div></body>")
        b = await compute_state(session.page)
    assert a.dom_hash != b.dom_hash
