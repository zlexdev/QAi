"""Destructive-action classifier — a heuristic, not a security guarantee.

Keyword match against a clickable element's visible text/aria-label (EN+RU). A
destructive-looking action is skipped by default (dry-run) unless explicitly
allowlisted by selector. This can miss novel phrasing — callers must review
``CrawlReport.skipped_destructive`` themselves, not treat this as exhaustive.
"""

from __future__ import annotations

_DESTRUCTIVE_KEYWORDS = (
    "delete", "удалить", "remove", "убрать", "удали",
    "pay", "оплатить", "payment", "оплата",
    "withdraw", "вывести", "вывод",
    "transfer", "перевести", "перевод",
    "purchase", "buy", "купить", "покупка",
    "cancel", "отменить", "отмена",
    "deactivate", "деактивировать",
    "unsubscribe", "отписаться",
    "close account", "закрыть счёт", "закрыть аккаунт",
)


def is_destructive(label: str | None) -> bool:
    """True if ``label`` (button text / aria-label) matches a destructive keyword."""
    if not label:
        return False
    lowered = label.strip().lower()
    return any(keyword in lowered for keyword in _DESTRUCTIVE_KEYWORDS)


def is_allowlisted(selector: str, allowlist: frozenset[str]) -> bool:
    return selector in allowlist
