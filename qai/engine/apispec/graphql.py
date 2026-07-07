"""parse_graphql — walks a GraphQL introspection JSON result or a raw SDL string into
``list[ApiOperation]``, one op per Query/Mutation field (Decision D9). Subscriptions
are skipped (documented, not an error — no HTTP-fuzzable request shape). Nested input
types are flattened one level (R-5, v1 limitation, matches HTML forms' own flat
field-set shape)."""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from qai.engine.apispec.contracts import ApiOperation, ApiParam, ApiSpecKind
from qai.engine.contracts import FieldConstraints, FieldKind, HttpMethod
from qai.engine.errors import InvalidSpecError

_SCALAR_KIND: dict[str, FieldKind] = {
    "Int": FieldKind.NUMBER,
    "Float": FieldKind.NUMBER,
    "String": FieldKind.TEXT,
    "Boolean": FieldKind.CHECKBOX,
    "ID": FieldKind.TEXT,
}


def _unwrap_type(type_ref: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Strips NON_NULL/LIST wrappers, returns (named_type, is_required)."""
    required = False
    current = type_ref
    while current.get("kind") in {"NON_NULL", "LIST"}:
        if current["kind"] == "NON_NULL":
            required = True
        current = current.get("ofType") or {}
    return current, required


def _arg_kind(named_type: dict[str, Any]) -> FieldKind:
    name = named_type.get("name")
    if name in _SCALAR_KIND:
        return _SCALAR_KIND[name]
    if named_type.get("kind") == "ENUM":
        return FieldKind.SELECT
    return FieldKind.TEXT  # INPUT_OBJECT (flattened one level) or unknown scalar


def _params_from_introspection_args(args: list[dict[str, Any]]) -> list[ApiParam]:
    params: list[ApiParam] = []
    for arg in args:
        named_type, required = _unwrap_type(arg["type"])
        params.append(
            ApiParam(
                name=arg["name"],
                kind=_arg_kind(named_type),
                required=required,
                constraints=FieldConstraints(required=required),
                location="arg",
            )
        )
        if named_type.get("kind") == "INPUT_OBJECT":
            for field in named_type.get("inputFields", []) or []:
                field_type, field_required = _unwrap_type(field["type"])
                params.append(
                    ApiParam(
                        name=f"{arg['name']}.{field['name']}",
                        kind=_arg_kind(field_type),
                        required=field_required,
                        constraints=FieldConstraints(required=field_required),
                        location="arg",
                    )
                )
    return params


def _parse_introspection(raw: str) -> list[ApiOperation]:
    try:
        doc = json.loads(raw)
        schema = doc["data"]["__schema"] if "data" in doc else doc["__schema"]
        types: list[dict[str, Any]] = schema["types"]
        query_type_name = (schema.get("queryType") or {}).get("name")
        mutation_type_name = (schema.get("mutationType") or {}).get("name")
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidSpecError(raw[:80], f"not a valid introspection result: {exc}") from exc

    operations: list[ApiOperation] = []
    for type_name, root_kind in ((query_type_name, "Query"), (mutation_type_name, "Mutation")):
        if not type_name:
            continue
        type_def = next((t for t in types if t.get("name") == type_name), None)
        if type_def is None:
            continue
        for field in type_def.get("fields") or []:
            operations.append(
                ApiOperation(
                    operation_id=f"{root_kind}.{field['name']}",
                    method=HttpMethod.POST,
                    path="/graphql",
                    params=_params_from_introspection_args(field.get("args", [])),
                    source=ApiSpecKind.GRAPHQL,
                )
            )
    return operations


_SDL_FIELD_RE = re.compile(r"^\s*(\w+)\s*(\(([^)]*)\))?\s*:\s*([\w!\[\]]+)", re.MULTILINE)
_SDL_ARG_RE = re.compile(r"(\w+)\s*:\s*([\w!\[\]]+)")
_SDL_TYPE_BLOCK_RE = re.compile(r"type\s+(Query|Mutation|Subscription)\s*\{([^}]*)\}")


def _sdl_arg_kind(type_token: str) -> FieldKind:
    bare = type_token.rstrip("!").strip("[]")
    return _SCALAR_KIND.get(bare, FieldKind.TEXT)


def _parse_sdl(raw: str) -> list[ApiOperation]:
    blocks = _SDL_TYPE_BLOCK_RE.findall(raw)
    if not blocks:
        raise InvalidSpecError(raw[:80], "no Query/Mutation/Subscription type block found")

    operations: list[ApiOperation] = []
    for root_kind, body in blocks:
        if root_kind == "Subscription":
            continue  # no HTTP-fuzzable request shape (Decision D9)
        for match in _SDL_FIELD_RE.finditer(body):
            field_name, _paren, args_raw, _return_type = match.groups()
            # _return_type's nullability doesn't affect fuzzing — only args do.
            params = [
                ApiParam(
                    name=arg_name,
                    kind=_sdl_arg_kind(arg_type),
                    required=arg_type.endswith("!"),
                    constraints=FieldConstraints(required=arg_type.endswith("!")),
                    location="arg",
                )
                for arg_name, arg_type in _SDL_ARG_RE.findall(args_raw or "")
            ]
            operations.append(
                ApiOperation(
                    operation_id=f"{root_kind}.{field_name}",
                    method=HttpMethod.POST,
                    path="/graphql",
                    params=params,
                    source=ApiSpecKind.GRAPHQL,
                )
            )
    return operations


def parse_graphql(
    raw: str, *, kind: Literal["introspection", "sdl"] = "introspection"
) -> list[ApiOperation]:
    if kind == "introspection":
        return _parse_introspection(raw)
    return _parse_sdl(raw)
