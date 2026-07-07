"""parse_graphql — introspection JSON + raw SDL, both walking Query/Mutation fields
into ApiOperations; Subscription fields are skipped."""

from __future__ import annotations

import json

import pytest

from qai.engine.apispec.graphql import parse_graphql
from qai.engine.contracts import FieldKind
from qai.engine.errors import InvalidSpecError

_INTROSPECTION = {
    "data": {
        "__schema": {
            "queryType": {"name": "Query"},
            "mutationType": {"name": "Mutation"},
            "types": [
                {
                    "name": "Query",
                    "fields": [
                        {
                            "name": "user",
                            "args": [
                                {
                                    "name": "id",
                                    "type": {"kind": "NON_NULL", "ofType": {"kind": "SCALAR", "name": "Int"}},
                                }
                            ],
                        }
                    ],
                },
                {
                    "name": "Mutation",
                    "fields": [
                        {
                            "name": "createUser",
                            "args": [
                                {
                                    "name": "name",
                                    "type": {"kind": "SCALAR", "name": "String"},
                                }
                            ],
                        }
                    ],
                },
            ],
        }
    }
}

_SDL = """
type Query {
  user(id: Int!): User
}

type Mutation {
  createUser(name: String!, age: Int): User
}

type Subscription {
  userCreated: User
}
"""


def test_parse_graphql_introspection_walks_query_and_mutation() -> None:
    operations = parse_graphql(json.dumps(_INTROSPECTION), kind="introspection")
    ids = {op.operation_id for op in operations}
    assert ids == {"Query.user", "Mutation.createUser"}


def test_parse_graphql_introspection_maps_arg_kinds() -> None:
    operations = parse_graphql(json.dumps(_INTROSPECTION), kind="introspection")
    user_op = next(op for op in operations if op.operation_id == "Query.user")
    id_param = next(p for p in user_op.params if p.name == "id")
    assert id_param.kind is FieldKind.NUMBER
    assert id_param.required is True


def test_parse_graphql_sdl_walks_query_and_mutation_skips_subscription() -> None:
    operations = parse_graphql(_SDL, kind="sdl")
    ids = {op.operation_id for op in operations}
    assert ids == {"Query.user", "Mutation.createUser"}
    assert not any(op.operation_id.startswith("Subscription") for op in operations)


def test_parse_graphql_sdl_maps_arg_required() -> None:
    operations = parse_graphql(_SDL, kind="sdl")
    create_user = next(op for op in operations if op.operation_id == "Mutation.createUser")
    by_name = {p.name: p for p in create_user.params}
    assert by_name["name"].required is True
    assert by_name["age"].required is False
    assert by_name["age"].kind is FieldKind.NUMBER


def test_malformed_introspection_raises_invalid_spec_error() -> None:
    with pytest.raises(InvalidSpecError):
        parse_graphql(json.dumps({"not": "a schema"}), kind="introspection")


def test_malformed_sdl_raises_invalid_spec_error() -> None:
    with pytest.raises(InvalidSpecError):
        parse_graphql("this is not SDL at all", kind="sdl")
