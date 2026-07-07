"""parse_openapi — walks an OpenAPI 3.x document's paths+operations into
``list[ApiOperation]``. Accepts JSON always (stdlib ``json``); YAML requires the
optional ``apispec`` extra (``pyyaml``) — see plan `05-risks.md` R-6."""

from __future__ import annotations

import json
from typing import Any, Literal

from qai.engine.apispec.contracts import ApiOperation, ApiParam, ApiSpecKind
from qai.engine.contracts import FieldConstraints, FieldKind, HttpMethod
from qai.engine.errors import InvalidSpecError

_HTTP_METHODS = {m.value.lower() for m in HttpMethod}


def _load_raw(raw: str) -> dict[str, Any]:
    try:
        doc: Any = json.loads(raw)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-untyped]
        except ImportError as exc:
            raise InvalidSpecError(
                raw[:80], "not valid JSON and PyYAML isn't installed (pip install qai[apispec])"
            ) from exc
        try:
            doc = yaml.safe_load(raw)
        except yaml.YAMLError as exc:
            raise InvalidSpecError(raw[:80], f"not valid JSON or YAML: {exc}") from exc
    if not isinstance(doc, dict):
        raise InvalidSpecError(raw[:80], "top-level document must be a JSON/YAML object")
    return doc


def _param_kind(schema: dict[str, Any]) -> FieldKind:
    schema_type = schema.get("type", "string")
    schema_format = schema.get("format")
    if schema.get("enum"):
        return FieldKind.SELECT
    if schema_type in {"integer", "number"}:
        return FieldKind.NUMBER
    if schema_type == "string" and schema_format == "email":
        return FieldKind.EMAIL
    if schema_type == "string" and schema_format == "date":
        return FieldKind.DATE
    return FieldKind.TEXT


def _param_constraints(schema: dict[str, Any], required: bool) -> FieldConstraints:
    return FieldConstraints(
        required=required,
        min_length=schema.get("minLength"),
        max_length=schema.get("maxLength"),
        minimum=schema.get("minimum"),
        maximum=schema.get("maximum"),
        pattern=schema.get("pattern"),
        options=[str(v) for v in schema.get("enum", [])],
    )


def _params_from_parameters(parameters: list[dict[str, Any]]) -> list[ApiParam]:
    out: list[ApiParam] = []
    for p in parameters:
        schema = p.get("schema", {})
        raw_location = p.get("in", "query")
        location: Literal["path", "query"] = raw_location if raw_location == "path" else "query"
        out.append(
            ApiParam(
                name=p["name"],
                kind=_param_kind(schema),
                required=bool(p.get("required", False)),
                constraints=_param_constraints(schema, bool(p.get("required", False))),
                location=location,
            )
        )
    return out


def _params_from_request_body(request_body: dict[str, Any]) -> list[ApiParam]:
    content: dict[str, Any] = request_body.get("content", {})
    default_media: dict[str, Any] = {}
    body_schema = next(iter(content.values()), default_media).get("schema", {})
    required_fields = set(body_schema.get("required", []))
    properties: dict[str, Any] = body_schema.get("properties", {})
    return [
        ApiParam(
            name=name,
            kind=_param_kind(prop_schema),
            required=name in required_fields,
            constraints=_param_constraints(prop_schema, name in required_fields),
            location="body",
        )
        for name, prop_schema in properties.items()
    ]


def parse_openapi(raw: str) -> list[ApiOperation]:
    doc = _load_raw(raw)
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        raise InvalidSpecError(raw[:80], "missing or invalid top-level 'paths' object")

    try:
        operations: list[ApiOperation] = []
        for path, path_item in paths.items():
            if not isinstance(path_item, dict):
                continue
            for method_raw, op in path_item.items():
                if method_raw.lower() not in _HTTP_METHODS or not isinstance(op, dict):
                    continue
                method = HttpMethod(method_raw.upper())
                operation_id = op.get("operationId") or f"{method_raw}_{path}"
                params = _params_from_parameters(op.get("parameters", []))
                request_body = op.get("requestBody")
                if isinstance(request_body, dict):
                    params += _params_from_request_body(request_body)
                operations.append(
                    ApiOperation(
                        operation_id=operation_id,
                        method=method,
                        path=path,
                        params=params,
                        source=ApiSpecKind.OPENAPI,
                    )
                )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidSpecError(raw[:80], f"malformed operation: {exc}") from exc
    return operations
