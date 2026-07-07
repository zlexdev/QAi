# apispec

Parses a spec-driven API surface (OpenAPI 3.x JSON/YAML, or GraphQL introspection
JSON/SDL) into `ApiOperation`s, then converts each to the engine's existing
`FormModel`/`FieldModel` vocabulary — so `fuzzer/`, `direct_executor.py`,
`analyzer.py`, and `reporter.py` run completely unmodified against API-scanned
operations (Decision B, see the plan's `00-decisions.md`).

## Public surface
- `contracts.py` — `ApiSpecKind`, `ApiParam`, `ApiOperation` (+ `.to_form_model()`),
  `ApiSpecSource`. All frozen (`_FROZEN` reused from `qai.engine.contracts`).
- `openapi.py` — `parse_openapi(raw: str) -> list[ApiOperation]`.
- `graphql.py` — `parse_graphql(raw: str, *, kind="introspection"|"sdl") -> list[ApiOperation]`.
- `convert.py` — `to_form_model(op: ApiOperation) -> FormModel`.

## Consumer
`qai/engine/api_runner.py::run_api_scan()` dispatches by `ApiSpecSource.kind`, converts
every operation, and fuzzes it via the SAME `_fuzz_form()` helper `run_scan` uses.

## Known v1 limitations (see plan `05-risks.md`)
- GraphQL nested input types flatten one level only (`input.field`, not deeper).
- GraphQL Subscription fields are skipped (no HTTP-fuzzable request shape).
- YAML OpenAPI specs require the optional `apispec` extra (`pip install qai[apispec]`,
  pulls in PyYAML) — JSON specs work with zero extra deps.
