from __future__ import annotations

import re

from qai.engine.contracts import ExpectedOutcome, FieldConstraints, FuzzIntent
from qai.engine.fuzzer.strategies import FieldFuzzStrategy


def test_pattern_violation_case_actually_violates_pattern() -> None:
    pattern = r"^[A-Za-z0-9_-]+$"
    cases = FieldFuzzStrategy._pattern_violation(FieldConstraints(pattern=pattern))

    assert len(cases) == 1
    case = cases[0]
    assert case.intent is FuzzIntent.SCHEMA_VIOLATION
    assert case.expect is ExpectedOutcome.REJECT_GRACEFULLY
    assert re.fullmatch(pattern, case.value) is None


def test_pattern_violation_is_empty_without_a_pattern() -> None:
    assert FieldFuzzStrategy._pattern_violation(FieldConstraints()) == []


def test_pattern_violation_is_empty_for_a_pattern_every_candidate_matches() -> None:
    # ".*" matches every candidate string, including the empty string — the helper
    # must give up cleanly rather than assert a false violation.
    assert FieldFuzzStrategy._pattern_violation(FieldConstraints(pattern=".*")) == []
