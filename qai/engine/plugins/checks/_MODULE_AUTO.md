# checks/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

> Importing this subpackage registers every built-in check as a side effect — same

## __init__.py
```
# Importing this subpackage registers every built-in check as a side effect — same


```

## auth_bypass.py
```
# AuthBypassCheck — active check: re-fires a captured request with auth stripped


cls AuthBypassCheck(Check)
  async run(ctx: CheckContext, replay: ReplayClient? = None) -> list[PluginFinding]

```

## differential.py
```
# Shared differential-response heuristic for the two active checks (IdorCheck,


_response_header(req: CapturedRequest, name: str) -> str | None

content_length(req: CapturedRequest) -> int | None

similar_shape(original: CapturedRequest, candidate: CapturedRequest) -> bool

```

## idor.py
```
# IdorCheck — active check: adjacent-id replay + differential response. Flags an

_NUMERIC_SEGMENT = str.isdigit

cls IdorCheck(Check)
  async run(ctx: CheckContext, replay: ReplayClient? = None) -> list[PluginFinding]

_path_segments(url: str) -> list[str]

_numeric_id_index(segments: list[str) -> int | None

_with_segment(url: str, index: int, new_value: str) -> str

```

## security_headers.py
```
# First passive check — inspects already-captured response headers for a missing

_REQUIRED_HEADERS = …

cls SecurityHeadersCheck(Check)
  async run(ctx: CheckContext, replay: object? = None) -> list[PluginFinding]

```
