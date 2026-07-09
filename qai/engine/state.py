"""State identity for the crawler — a URL alone can't identify an SPA's in-memory
state, so identity is (normalized URL, structural DOM hash). The hash walks
tag/role/hierarchy only — never text content or timestamps, which would otherwise
make a paginated list or a live clock look like infinite unique states —
dedup is the main trap here.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import Page

from qai.engine.contracts import StateRef

# Matches a path segment that is an opaque record id, not a distinct page shape:
# all-digits ("2290") or UUID-shaped (8-4-4-4-12 hex). Anything else (slugs like
# "user-settings") is left alone — it's a real distinct page, not a template instance.
_ID_SEGMENT_RE = re.compile(
    r"^\d+$|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

# Walks the DOM emitting only tag name + explicit/implicit role + child count per node —
# no text, no attribute values (both vary with data, not structure).
_STRUCTURAL_SIGNATURE_JS = r"""
() => {
  const sig = (el, depth) => {
    if (depth > 40) return '';
    const tag = el.tagName ? el.tagName.toLowerCase() : '?';
    const role = el.getAttribute ? (el.getAttribute('role') || '') : '';
    const kids = Array.from(el.children || []);
    return tag + ':' + role + ':' + kids.length + '[' + kids.map(k => sig(k, depth + 1)).join(',') + ']';
  };
  return sig(document.documentElement, 0);
}
"""


def normalize_url(url: str) -> str:
    """Strip fragment (SPA router hash aside) and trailing slash for stable comparison."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def is_in_scope(url: str, root_host: str, *, include_subdomains: bool) -> bool:
    """True if ``url``'s host is ``root_host`` itself, or (when allowed) a subdomain
    of it. Used by the crawler to keep BFS discovery on the target site instead of
    wandering off into footer/nav links to unrelated domains (Telegram, GitHub, ...)."""
    host = (urlsplit(url).hostname or "").lower()
    root = root_host.lower()
    if not host or not root:
        return False
    if host == root:
        return True
    return include_subdomains and host.endswith(f".{root}")


def is_in_scope_any(url: str, allowed_hosts: Iterable[str], *, include_subdomains: bool) -> bool:
    """``is_in_scope`` against a set of allowed hosts — the crawl's own root plus any
    extra ``CrawlBudget.allowed_domains`` (e.g. a separate auth/SSO or API subdomain
    that isn't a subdomain of the root)."""
    return any(
        is_in_scope(url, host, include_subdomains=include_subdomains) for host in allowed_hosts
    )


def url_template(url: str) -> str:
    """Path shape with every id-like segment collapsed to ``#`` — groups
    ``/lots/2290``, ``/lots/3031``, ... as one template so the crawler doesn't spend
    its whole budget visiting hundreds of structurally identical listing pages
    (found live on funpay.com: 900+ ``/lots/<id>`` pages ate the entire wall-clock
    budget before any form ever got fuzzed)."""
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    template = "/".join("#" if _ID_SEGMENT_RE.match(s) else s for s in segments)
    return f"{parts.netloc}/{template}"


async def compute_state(page: Page, checkpoint_id: str = "root") -> StateRef:
    signature: str = await page.evaluate(_STRUCTURAL_SIGNATURE_JS)
    dom_hash = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
    return StateRef(
        normalized_url=normalize_url(page.url), dom_hash=dom_hash, checkpoint_id=checkpoint_id
    )
