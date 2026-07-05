"""DataGenerator — turns a form's fields into an ordered list of fuzz plans.

Each plan holds a "baseline" valid value for every field plus ONE field under test carrying
a single fuzz case. Submitting one field's abuse at a time (rest valid) isolates which field
triggers a server error — the correlation the report needs.
"""

from __future__ import annotations

from dataclasses import dataclass

from qai.engine.contracts import (
    ExpectedOutcome,
    FieldModel,
    FormModel,
    FuzzCase,
    FuzzIntent,
)
from qai.engine.fuzzer.strategies import strategy_for


@dataclass(frozen=True, slots=True)
class FuzzPlan:
    """One form submission: baseline values for all fields + one field under test."""

    case_id: str
    field_under_test: FieldModel
    case: FuzzCase
    values: dict[str, str]  # selector -> value to type


class DataGenerator:
    """Builds the fuzz matrix for a form."""

    def plans(self, form: FormModel) -> list[FuzzPlan]:
        baseline = {f.selector: self._baseline(f) for f in form.fields}
        out: list[FuzzPlan] = []
        for field in form.fields:
            for i, case in enumerate(strategy_for(field.kind).variants(field)):
                values = dict(baseline)
                values[field.selector] = case.value
                case_id = f"{form.group_id}::{field.selector}::{case.intent.value}::{i}"
                out.append(
                    FuzzPlan(
                        case_id=case_id,
                        field_under_test=field,
                        case=case,
                        values=values,
                    )
                )
        return out

    def _baseline(self, field: FieldModel) -> str:
        for case in strategy_for(field.kind).variants(field):
            if case.intent is FuzzIntent.VALID:
                return case.value
        return ""


__all__ = ["DataGenerator", "ExpectedOutcome", "FuzzPlan"]
