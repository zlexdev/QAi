# apispec/
<!-- AUTO-GENERATED. Do not edit. Run gen_module_auto.py to update. -->

> apispec — OpenAPI/GraphQL spec parsing, converted to the existing FormModel/

## __init__.py
```
# apispec — OpenAPI/GraphQL spec parsing, converted to the existing FormModel/


```

## contracts.py
```
# apispec contracts — OpenAPI/GraphQL operations converted to the EXISTING


cls ApiSpecKind(StrEnum): OPENAPI, GRAPHQL

cls ApiParam(BaseModel)

cls ApiOperation(BaseModel)
  to_form_model() -> FormModel

cls ApiSpecSource(BaseModel)

```

## convert.py
```
# ApiOperation -> FormModel converter — the reuse seam (Decision B): once an


to_form_model(op: ApiOperation) -> FormModel

```

## graphql.py
```
# parse_graphql — walks a GraphQL introspection JSON result or a raw SDL string into

_SDL_FIELD_RE = …
_SDL_ARG_RE = re.compile('(\\w+)\\s*:\\s*([\\w!\\[\\]]+)')
_SDL_TYPE_BLOCK_RE = …

_unwrap_type(type_ref: dict[str, Any) -> tuple[dict[str, Any], bool]
  # Strips NON_NULL/LIST wrappers, returns (named_type, is_required).

_arg_kind(named_type: dict[str, Any) -> FieldKind

_params_from_introspection_args(args: list[dict[str, Any) -> list[ApiParam]

_parse_introspection(raw: str) -> list[ApiOperation]

_sdl_arg_kind(type_token: str) -> FieldKind

_parse_sdl(raw: str) -> list[ApiOperation]

parse_graphql(raw: str) -> list[ApiOperation]

```

## openapi.py
```
# parse_openapi — walks an OpenAPI 3.x document's paths+operations into

_HTTP_METHODS = {m.value.lower() for m in HttpMethod}

_load_raw(raw: str) -> dict[str, Any]

_param_kind(schema: dict[str, Any) -> FieldKind

_param_constraints(schema: dict[str, Any, required: bool) -> FieldConstraints

_params_from_parameters(parameters: list[dict[str, Any) -> list[ApiParam]

_params_from_request_body(request_body: dict[str, Any) -> list[ApiParam]

parse_openapi(raw: str) -> list[ApiOperation]

```
