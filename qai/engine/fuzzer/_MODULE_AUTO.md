# fuzzer/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

## generator.py
```
# DataGenerator — turns a form's fields into an ordered list of fuzz plans.


cls FuzzPlan: case_id: str, field_under_test: FieldModel, case: FuzzCase, values: dict[str, str]
  # One form submission: baseline values for all fields + one field under test.

cls DataGenerator
  # Builds the fuzz matrix for a form.
  plans(form: FormModel) -> list[FuzzPlan]

```

## strategies.py
```
# Per-field-type fuzz strategies — one class per :class:`FieldKind`, open-closed.

_OVERFLOW_LEN = 100000
_MALICIOUS = …
_UNICODE = '𝕏🔥💥\u202eabc\ufeff'
_PATTERN_VIOLATION_CANDIDATES = …

cls FieldFuzzStrategy(ABC)
  # Base seam: produce fuzz cases for one field kind.
  variants(field: FieldModel) -> list[FuzzCase]

cls TextStrategy(FieldFuzzStrategy)
  variants(field: FieldModel) -> list[FuzzCase]

cls NumberStrategy(FieldFuzzStrategy)
  variants(field: FieldModel) -> list[FuzzCase]

cls EmailStrategy(FieldFuzzStrategy)
  variants(field: FieldModel) -> list[FuzzCase]

cls DateStrategy(FieldFuzzStrategy)
  variants(field: FieldModel) -> list[FuzzCase]

cls SelectStrategy(FieldFuzzStrategy)
  variants(field: FieldModel) -> list[FuzzCase]

cls ToggleStrategy(FieldFuzzStrategy)
  variants(field: FieldModel) -> list[FuzzCase]

cls FileStrategy(FieldFuzzStrategy)
  variants(field: FieldModel) -> list[FuzzCase]

register(kind: FieldKind) -> Callable[[type[FieldFuzzStrategy]], type[FieldFuzzStrategy]]

strategy_for(kind: FieldKind) -> FieldFuzzStrategy
  # Return the strategy for ``kind``, falling back to the text strategy.

```
