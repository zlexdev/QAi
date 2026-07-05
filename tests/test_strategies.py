from __future__ import annotations

from qai.engine.contracts import (
    FieldConstraints,
    FieldKind,
    FieldModel,
    FuzzIntent,
)
from qai.engine.fuzzer.generator import DataGenerator
from qai.engine.fuzzer.strategies import strategy_for


def _field(kind: FieldKind, **constraints: object) -> FieldModel:
    return FieldModel(
        selector=f"#{kind.value}",
        kind=kind,
        group_id="g1",
        constraints=FieldConstraints(**constraints),
    )


def test_text_strategy_includes_overflow_and_malicious() -> None:
    field = _field(FieldKind.TEXT)
    intents = {c.intent for c in strategy_for(FieldKind.TEXT).variants(field)}
    assert FuzzIntent.OVERFLOW in intents
    assert FuzzIntent.MALICIOUS in intents
    assert FuzzIntent.VALID in intents


def test_number_strategy_respects_bounds() -> None:
    field = _field(FieldKind.NUMBER, minimum=0, maximum=120)
    cases = strategy_for(FieldKind.NUMBER).variants(field)
    boundary_values = {c.value for c in cases if c.intent is FuzzIntent.BOUNDARY}
    assert "121" in boundary_values
    assert "-1" in boundary_values


def test_generator_isolates_one_field_per_plan() -> None:
    from qai.engine.contracts import FormModel

    name = _field(FieldKind.TEXT, required=True)
    age = _field(FieldKind.NUMBER, minimum=0, maximum=120)
    form = FormModel(group_id="signup", submit_selector="#submit", fields=[name, age])

    plans = DataGenerator().plans(form)
    assert plans
    for plan in plans:
        # every other field falls back to its own baseline (valid) value
        for selector, value in plan.values.items():
            if selector != plan.field_under_test.selector:
                assert value != "", "baseline fields must stay valid, not empty"
