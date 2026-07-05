"""PageModeler — inventory of fields, types and form groups from a live page.

Self-contained: reads the DOM via one ``page.evaluate`` call (no Stagehand / Node runtime,
per PLAN CUT#4). Grouping uses static DOM signals — ``<form>`` boundaries, ``label[for]``,
``name`` — which cover the MVP's single-form target.
"""

from __future__ import annotations

from typing import Any

from playwright.async_api import Page

from qai.engine.contracts import (
    FieldConstraints,
    FieldKind,
    FieldModel,
    FormModel,
    HttpMethod,
    PageModel,
)
from qai.engine.logging import get_logger

_log = get_logger("modeler")

# Shared by both scripts below: a selector must be unique across the WHOLE document,
# not just among its parent's children — a bare `tag:nth-of-type(n)` matches every
# element that happens to be the n-th child of *its own* parent anywhere on the page,
# which caused the executor to fill the wrong field entirely on real, complex pages
# (found live: multiple orphan-clustered fields collided on `input:nth-of-type(1)`).
# Building the full ancestor-anchored path (or an id/unique-name shortcut) fixes that.
_SELECTOR_FOR_JS = r"""
  const selectorFor = (el) => {
    if (el.id) return '#' + cssEscape(el.id);
    if (el.name) {
      const byName = el.tagName.toLowerCase() + '[name="' + el.name + '"]';
      if (document.querySelectorAll(byName).length === 1) return byName;
    }
    const segments = [];
    let cur = el;
    while (cur && cur.nodeType === 1) {
      if (cur.id) {
        segments.unshift('#' + cssEscape(cur.id));
        break;
      }
      const parent = cur.parentElement;
      if (!parent) {
        segments.unshift(cur.tagName.toLowerCase());
        break;
      }
      const sameTag = Array.from(parent.children).filter(c => c.tagName === cur.tagName);
      const idx = sameTag.indexOf(cur) + 1;
      segments.unshift(cur.tagName.toLowerCase() + ':nth-of-type(' + idx + ')');
      cur = parent;
    }
    return segments.join(' > ');
  };
"""

# Shared by both scripts: aria-hidden/CSS-hidden "focus catcher" clones are real DOM
# nodes our selectors can match, but the executor can never fill/click them —
# Playwright times out (3-5s per attempt) on every fuzz case against one, silently
# burning most of a run's time budget (found live on a real site's mobile-header
# search clone: ~25 malicious cases each timed out on an invisible element).
_IS_VISIBLE_JS = r"""
  const isVisible = (el) => {
    if (el.getAttribute('aria-hidden') === 'true' || el.hasAttribute('hidden')) return false;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 0 || rect.height > 0;
  };
"""

# Runs in the page: returns a plain JSON tree of forms + fields with a stable selector each.
_EXTRACT_JS = (
    r"""
() => {
  const cssEscape = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
"""
    + _SELECTOR_FOR_JS
    + _IS_VISIBLE_JS
    + r"""
  const labelFor = (el) => {
    if (el.id) {
      const l = document.querySelector('label[for="' + (window.CSS?CSS.escape(el.id):el.id) + '"]');
      if (l) return l.innerText.trim();
    }
    const wrap = el.closest('label');
    if (wrap) return wrap.innerText.trim();
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label');
    if (el.placeholder) return el.placeholder;
    return null;
  };
  const kindOf = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'textarea') return 'textarea';
    if (tag === 'select') return 'select';
    if (tag === 'input') {
      const t = (el.getAttribute('type') || 'text').toLowerCase();
      const known = ['text','number','email','password','date','checkbox','radio','file'];
      if (known.includes(t)) return t;
      if (t === 'tel' || t === 'url' || t === 'search') return 'text';
      if (t === 'range') return 'number';  // semantically numeric (has min/max/step)
      return 'unknown';
    }
    return 'unknown';
  };
  const fieldOf = (el) => ({
    selector: selectorFor(el),
    name: el.name || null,
    kind: kindOf(el),
    label: labelFor(el),
    required: el.required || false,
    minLength: el.minLength > 0 ? el.minLength : null,
    maxLength: (el.maxLength && el.maxLength > 0) ? el.maxLength : null,
    min: el.min !== '' && el.min != null ? el.min : null,
    max: el.max !== '' && el.max != null ? el.max : null,
    pattern: el.pattern || null,
    options: tagOptions(el),
  });
  function tagOptions(el) {
    if (el.tagName.toLowerCase() !== 'select') return [];
    return Array.from(el.options).map(o => o.value).filter(v => v !== '');
  }
  const isControl = (el) => ['input','select','textarea'].includes(el.tagName.toLowerCase())
      && !['hidden','submit','button','reset','image'].includes((el.getAttribute('type')||'').toLowerCase())
      && isVisible(el);
  const isSubmitLike = (el) => {
    if (!isVisible(el)) return false;
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' && (el.getAttribute('type')||'').toLowerCase() === 'submit') return true;
    if (tag === 'button' && (el.getAttribute('type')||'').toLowerCase() !== 'reset') return true;
    return el.getAttribute('role') === 'button';
  };
  const forms = [];
  document.querySelectorAll('form').forEach((form, i) => {
    const fields = Array.from(form.querySelectorAll('input,select,textarea')).filter(isControl).map(fieldOf);
    const submit = form.querySelector('button[type="submit"],input[type="submit"],button:not([type])');
    forms.push({
      groupId: form.id || ('form-' + i),
      submitSelector: submit ? selectorFor(submit) : null,
      action: form.getAttribute('action'),
      method: (form.getAttribute('method') || 'post').toUpperCase(),
      fields,
    });
  });

  // Signal 2 (SPA, no <form> wrapper): cluster orphan fields to the nearest
  // orphan submit-like button by common-ancestor distance, since without this a
  // page with 2+ button-driven "forms" would wrongly dump every field into one bucket.
  const orphanFields = Array.from(document.querySelectorAll('input,select,textarea'))
      .filter(isControl).filter(el => !el.closest('form'));
  const orphanButtons = Array.from(document.querySelectorAll('button,[role="button"],input[type="submit"]'))
      .filter(isSubmitLike).filter(el => !el.closest('form'));

  const ancestorsOf = (el) => {
    const chain = [];
    let cur = el;
    while (cur) { chain.push(cur); cur = cur.parentElement; }
    return chain;
  };
  const commonAncestorDistance = (a, b) => {
    const pathA = ancestorsOf(a);
    const pathB = ancestorsOf(b);
    const setA = new Map(pathA.map((el, idx) => [el, idx]));
    for (let j = 0; j < pathB.length; j++) {
      if (setA.has(pathB[j])) return setA.get(pathB[j]) + j;
    }
    return Infinity;
  };

  if (orphanButtons.length > 1) {
    orphanButtons.forEach((btn, i) => {
      const claimed = orphanFields.filter(f =>
        orphanButtons.reduce((best, cand, ci) => {
          const d = commonAncestorDistance(f, cand);
          return d < best.d ? { d, i: ci } : best;
        }, { d: Infinity, i: -1 }).i === i
      ).map(fieldOf);
      if (claimed.length) {
        forms.push({ groupId: 'btn-' + i, submitSelector: selectorFor(btn),
                     action: null, method: 'POST', fields: claimed });
      }
    });
  } else if (orphanFields.length) {
    const submit = orphanButtons[0];
    forms.push({ groupId: 'standalone', submitSelector: submit ? selectorFor(submit) : null,
                 action: null, method: 'POST', fields: orphanFields.map(fieldOf) });
  }
  return forms;
}
"""
)


_DISCOVER_ACTIONS_JS = (
    r"""
() => {
  const cssEscape = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s.replace(/[^a-zA-Z0-9_-]/g, '\\$&');
"""
    + _SELECTOR_FOR_JS
    + _IS_VISIBLE_JS
    + r"""
  const labelOf = (el) => (el.innerText || el.getAttribute('aria-label') || el.value || '').trim();
  const links = Array.from(document.querySelectorAll('a[href]')).filter(isVisible).map(el => {
    let abs = null;
    try { abs = new URL(el.getAttribute('href'), location.href).href; } catch (e) { abs = null; }
    return { kind: 'link', selector: selectorFor(el), label: labelOf(el), href: abs };
  }).filter(l => l.href && l.href.startsWith('http'));
  const buttons = Array.from(document.querySelectorAll('button,[role="button"],input[type="submit"]'))
      .filter(el => !el.closest('form') && isVisible(el))
      .map(el => ({ kind: 'button', selector: selectorFor(el), label: labelOf(el), href: null }));
  return [...links, ...buttons];
}
"""
)


class PageModeler:
    """Extracts a typed :class:`PageModel` from a loaded Playwright page."""

    async def model(self, page: Page) -> PageModel:
        raw: list[dict[str, Any]] = await page.evaluate(_EXTRACT_JS)
        forms = [self._form(f) for f in raw if f.get("fields")]
        _log.info("page_modeled", url=page.url, forms=len(forms))
        return PageModel(url=page.url, forms=forms)

    async def discover_actions(self, page: Page) -> list[dict[str, Any]]:
        """Links + standalone buttons (not inside a `<form>`) — candidates for the
        crawler to follow. Form submits are handled by the fuzzing pass instead."""
        result: list[dict[str, Any]] = await page.evaluate(_DISCOVER_ACTIONS_JS)
        return result

    def _form(self, data: dict[str, Any]) -> FormModel:
        group_id = str(data["groupId"])
        return FormModel(
            group_id=group_id,
            submit_selector=data.get("submitSelector"),
            action=data.get("action"),
            method=_method(data.get("method")),
            fields=[self._field(f, group_id) for f in data["fields"]],
        )

    def _field(self, data: dict[str, Any], group_id: str) -> FieldModel:
        return FieldModel(
            selector=data["selector"],
            name=data.get("name"),
            kind=_kind(data.get("kind")),
            label=data.get("label"),
            group_id=group_id,
            constraints=FieldConstraints(
                required=bool(data.get("required")),
                min_length=data.get("minLength"),
                max_length=data.get("maxLength"),
                minimum=_num(data.get("min")),
                maximum=_num(data.get("max")),
                pattern=data.get("pattern"),
                options=list(data.get("options") or []),
            ),
        )


def _kind(raw: str | None) -> FieldKind:
    try:
        return FieldKind(raw) if raw else FieldKind.UNKNOWN
    except ValueError:
        return FieldKind.UNKNOWN


def _method(raw: str | None) -> HttpMethod:
    try:
        return HttpMethod((raw or "POST").upper())
    except ValueError:
        return HttpMethod.POST


def _num(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
