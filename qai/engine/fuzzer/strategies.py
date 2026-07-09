"""Per-field-type fuzz strategies — one class per :class:`FieldKind`, open-closed.

Registry seam (load-bearing per PLAN §Шов): a new field type = a new ``@register`` class,
no edits to the generator. Each strategy turns a field's constraints into a matrix of
:class:`FuzzCase` covering valid / empty / boundary / overflow / malicious / unicode intents.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable

from qai.engine.contracts import (
    ExpectedOutcome,
    FieldConstraints,
    FieldKind,
    FieldModel,
    FuzzCase,
    FuzzIntent,
)

_OVERFLOW_LEN = 100_000
_MALICIOUS = [
    # SQL injection
    "' OR '1'='1",
    "'; DROP TABLE users;--",
    "1' UNION SELECT NULL,NULL,NULL--",
    # XSS
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "javascript:alert(1)",
    # Path traversal — raw and URL-encoded (a validator that only blocks "../" misses this)
    "../../../../etc/passwd",
    "..%2f..%2f..%2f..%2fetc%2fpasswd",
    "..\\..\\..\\..\\windows\\win.ini",
    # Template injection — different engines use different delimiters
    "${{7*7}}",
    "{{7*7}}",
    "#{7*7}",
    "<%= 7*7 %>",
    # NoSQL injection (MongoDB-style operators reaching a query unescaped)
    '{"$ne": null}',
    '{"$gt": ""}',
    # OS command injection
    "; whoami",
    "$(whoami)",
    "`id`",
    "| cat /etc/passwd",
    # CRLF / header injection — a value later echoed into a response header
    "value\r\nSet-Cookie: injected=1",
    "value\nX-Injected: true",
    # Null byte — truncates C-string-backed validators/file paths downstream
    "valid\x00.jpg",
    # LDAP injection
    "*)(uid=*))(|(uid=*",
]
# Mathematical double-struck X, emoji, a right-to-left override char, and a BOM —
# the unicode edge cases a naive byte-length or ASCII-only validator chokes on.
_UNICODE = "\U0001d54f\U0001f525\U0001f4a5‮abc﻿"
# Candidates for _pattern_violation, cheapest/most-likely-to-fail first — each is only
# used if it actually fails re.fullmatch against the field's real pattern (never a guess).
_PATTERN_VIOLATION_CANDIDATES = ("", " ", "\x00", "!!!invalid!!!", _UNICODE, "A" * 5000)

_REGISTRY: dict[FieldKind, FieldFuzzStrategy] = {}


class FieldFuzzStrategy(ABC):
    """Base seam: produce fuzz cases for one field kind."""

    @abstractmethod
    def variants(self, field: FieldModel) -> list[FuzzCase]: ...

    @staticmethod
    def _maybe_empty(c: FieldConstraints) -> list[FuzzCase]:
        expect = ExpectedOutcome.REJECT_GRACEFULLY if c.required else ExpectedOutcome.ACCEPT
        return [FuzzCase(value="", intent=FuzzIntent.EMPTY, expect=expect)]

    @staticmethod
    def _malicious() -> list[FuzzCase]:
        return [
            FuzzCase(value=v, intent=FuzzIntent.MALICIOUS, expect=ExpectedOutcome.REJECT_GRACEFULLY)
            for v in _MALICIOUS
        ]

    @staticmethod
    def _pattern_violation(c: FieldConstraints) -> list[FuzzCase]:
        """Negative-testing case (idea ported from Schemathesis, MIT — see README "How
        it works"): find a value that provably fails the field's JSON-schema `pattern`
        and assert the API rejects it, instead of only testing pattern-conforming input."""
        if not c.pattern:
            return []
        try:
            regex = re.compile(c.pattern)
        except re.error:
            return []
        for candidate in _PATTERN_VIOLATION_CANDIDATES:
            if not regex.fullmatch(candidate):
                return [
                    FuzzCase(
                        value=candidate,
                        intent=FuzzIntent.SCHEMA_VIOLATION,
                        expect=ExpectedOutcome.REJECT_GRACEFULLY,
                    )
                ]
        return []


def register(
    kind: FieldKind,
) -> Callable[[type[FieldFuzzStrategy]], type[FieldFuzzStrategy]]:
    def deco(cls: type[FieldFuzzStrategy]) -> type[FieldFuzzStrategy]:
        _REGISTRY[kind] = cls()
        return cls

    return deco


def strategy_for(kind: FieldKind) -> FieldFuzzStrategy:
    """Return the strategy for ``kind``, falling back to the text strategy."""
    return _REGISTRY.get(kind, _REGISTRY[FieldKind.TEXT])


@register(FieldKind.TEXT)
@register(FieldKind.TEXTAREA)
@register(FieldKind.PASSWORD)
@register(FieldKind.UNKNOWN)
class TextStrategy(FieldFuzzStrategy):
    def variants(self, field: FieldModel) -> list[FuzzCase]:
        c = field.constraints
        cases = [FuzzCase(value="valid text", intent=FuzzIntent.VALID, expect=ExpectedOutcome.ACCEPT)]
        cases += self._maybe_empty(c)
        overflow_len = (c.max_length + 1000) if c.max_length else _OVERFLOW_LEN
        cases.append(
            FuzzCase(
                value="A" * overflow_len,
                intent=FuzzIntent.OVERFLOW,
                expect=ExpectedOutcome.REJECT_GRACEFULLY,
            )
        )
        cases.append(
            FuzzCase(value=_UNICODE, intent=FuzzIntent.UNICODE, expect=ExpectedOutcome.EITHER)
        )
        cases += self._malicious()
        cases += self._pattern_violation(c)
        return cases


@register(FieldKind.NUMBER)
class NumberStrategy(FieldFuzzStrategy):
    def variants(self, field: FieldModel) -> list[FuzzCase]:
        c = field.constraints
        cases = [FuzzCase(value="42", intent=FuzzIntent.VALID, expect=ExpectedOutcome.ACCEPT)]
        cases += self._maybe_empty(c)
        if c.maximum is not None:
            cases.append(
                FuzzCase(
                    value=str(int(c.maximum) + 1),
                    intent=FuzzIntent.BOUNDARY,
                    expect=ExpectedOutcome.REJECT_GRACEFULLY,
                )
            )
        if c.minimum is not None:
            cases.append(
                FuzzCase(
                    value=str(int(c.minimum) - 1),
                    intent=FuzzIntent.BOUNDARY,
                    expect=ExpectedOutcome.REJECT_GRACEFULLY,
                )
            )
        cases += [
            FuzzCase(
                value="99999999999999999999999", intent=FuzzIntent.OVERFLOW,
                expect=ExpectedOutcome.REJECT_GRACEFULLY
            ),
            FuzzCase(value="-1", intent=FuzzIntent.BOUNDARY, expect=ExpectedOutcome.EITHER),
            FuzzCase(
                value="not-a-number", intent=FuzzIntent.MALICIOUS,
                expect=ExpectedOutcome.REJECT_GRACEFULLY
            ),
            FuzzCase(value="1e309", intent=FuzzIntent.OVERFLOW, expect=ExpectedOutcome.REJECT_GRACEFULLY),
            # Signed 32/64-bit integer boundaries — a backend storing this in a fixed-
            # width column silently wraps/truncates right past these, unlike Python's
            # arbitrary-precision ints which happily accept anything.
            FuzzCase(value="2147483648", intent=FuzzIntent.BOUNDARY, expect=ExpectedOutcome.EITHER),
            FuzzCase(value="-2147483649", intent=FuzzIntent.BOUNDARY, expect=ExpectedOutcome.EITHER),
            FuzzCase(value="9223372036854775808", intent=FuzzIntent.BOUNDARY, expect=ExpectedOutcome.EITHER),
            # IEEE-754 special values — a naive `float(x)` parser accepts these as valid
            # numbers, but they usually break arithmetic/comparisons/serialization downstream.
            FuzzCase(value="NaN", intent=FuzzIntent.MALICIOUS, expect=ExpectedOutcome.REJECT_GRACEFULLY),
            FuzzCase(value="Infinity", intent=FuzzIntent.MALICIOUS, expect=ExpectedOutcome.REJECT_GRACEFULLY),
            FuzzCase(value="-0", intent=FuzzIntent.BOUNDARY, expect=ExpectedOutcome.EITHER),
            # Leading zeros can be misread as octal by a loose parser (e.g. "010" -> 8).
            FuzzCase(value="0010", intent=FuzzIntent.MALICIOUS, expect=ExpectedOutcome.EITHER),
            # Numeric-looking but not: hex/scientific notation a strict int-only field
            # should reject, not silently coerce.
            FuzzCase(value="0x2A", intent=FuzzIntent.MALICIOUS, expect=ExpectedOutcome.REJECT_GRACEFULLY),
            FuzzCase(value="1e5", intent=FuzzIntent.MALICIOUS, expect=ExpectedOutcome.EITHER),
        ]
        cases += self._pattern_violation(c)
        return cases


@register(FieldKind.EMAIL)
class EmailStrategy(FieldFuzzStrategy):
    def variants(self, field: FieldModel) -> list[FuzzCase]:
        cases = [
            FuzzCase(value="user@example.com", intent=FuzzIntent.VALID, expect=ExpectedOutcome.ACCEPT),
            FuzzCase(
                value="not-an-email", intent=FuzzIntent.MALICIOUS,
                expect=ExpectedOutcome.REJECT_GRACEFULLY
            ),
            FuzzCase(
                value="a@" + "b" * _OVERFLOW_LEN + ".com", intent=FuzzIntent.OVERFLOW,
                expect=ExpectedOutcome.REJECT_GRACEFULLY
            ),
        ]
        cases += self._maybe_empty(field.constraints)
        cases += self._malicious()
        cases += self._pattern_violation(field.constraints)
        return cases


@register(FieldKind.DATE)
class DateStrategy(FieldFuzzStrategy):
    def variants(self, field: FieldModel) -> list[FuzzCase]:
        cases = [
            FuzzCase(value="2026-01-15", intent=FuzzIntent.VALID, expect=ExpectedOutcome.ACCEPT),
            FuzzCase(
                value="0000-00-00", intent=FuzzIntent.BOUNDARY,
                expect=ExpectedOutcome.REJECT_GRACEFULLY
            ),
            FuzzCase(
                value="9999-99-99", intent=FuzzIntent.MALICIOUS,
                expect=ExpectedOutcome.REJECT_GRACEFULLY
            ),
            FuzzCase(
                value="not-a-date", intent=FuzzIntent.MALICIOUS,
                expect=ExpectedOutcome.REJECT_GRACEFULLY
            ),
        ]
        cases += self._maybe_empty(field.constraints)
        return cases


@register(FieldKind.SELECT)
class SelectStrategy(FieldFuzzStrategy):
    def variants(self, field: FieldModel) -> list[FuzzCase]:
        opts = field.constraints.options
        cases: list[FuzzCase] = []
        if opts:
            cases.append(FuzzCase(value=opts[0], intent=FuzzIntent.VALID, expect=ExpectedOutcome.ACCEPT))
        cases.append(
            FuzzCase(
                value="__not_an_option__", intent=FuzzIntent.SCHEMA_VIOLATION,
                expect=ExpectedOutcome.REJECT_GRACEFULLY
            )
        )
        return cases


@register(FieldKind.CHECKBOX)
@register(FieldKind.RADIO)
class ToggleStrategy(FieldFuzzStrategy):
    def variants(self, field: FieldModel) -> list[FuzzCase]:
        return [
            FuzzCase(value="on", intent=FuzzIntent.VALID, expect=ExpectedOutcome.ACCEPT),
            FuzzCase(value="", intent=FuzzIntent.EMPTY, expect=ExpectedOutcome.EITHER),
        ]


@register(FieldKind.FILE)
class FileStrategy(FieldFuzzStrategy):
    def variants(self, field: FieldModel) -> list[FuzzCase]:
        # File inputs need real paths; MVP skips upload fuzzing (Phase 4).
        return []
