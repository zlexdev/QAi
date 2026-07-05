"""State identity for the crawler — a URL alone can't identify an SPA's in-memory
state, so identity is (normalized URL, structural DOM hash). The hash walks
tag/role/hierarchy only — never text content or timestamps, which would otherwise
make a paginated list or a live clock look like infinite unique states
(mini-plat.md's own "dedup is the main trap" gotcha).
"""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit, urlunsplit

from playwright.async_api import Page

from qai.engine.contracts import StateRef

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


async def compute_state(page: Page, checkpoint_id: str = "root") -> StateRef:
    signature: str = await page.evaluate(_STRUCTURAL_SIGNATURE_JS)
    dom_hash = hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]
    return StateRef(
        normalized_url=normalize_url(page.url), dom_hash=dom_hash, checkpoint_id=checkpoint_id
    )
