"""parse_openapi + ApiOperation.to_form_model() against the bundled demo spec."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qai.engine.apispec.openapi import parse_openapi
from qai.engine.contracts import FieldKind
from qai.engine.errors import InvalidSpecError

_SPEC_PATH = Path(__file__).resolve().parents[1] / "qai" / "demo_target" / "openapi.json"


def test_parse_openapi_walks_bundled_demo_spec() -> None:
    raw = _SPEC_PATH.read_text()
    operations = parse_openapi(raw)
    ids = {op.operation_id for op in operations}
    assert {"searchItems", "echoPayload", "getItem"} <= ids


def test_query_param_type_mapping() -> None:
    operations = parse_openapi(_SPEC_PATH.read_text())
    search = next(op for op in operations if op.operation_id == "searchItems")
    by_name = {p.name: p for p in search.params}
    assert by_name["q"].kind is FieldKind.TEXT
    assert by_name["limit"].kind is FieldKind.NUMBER
    assert by_name["limit"].constraints.maximum == 100


def test_body_param_from_request_body() -> None:
    operations = parse_openapi(_SPEC_PATH.read_text())
    echo = next(op for op in operations if op.operation_id == "echoPayload")
    message_param = next(p for p in echo.params if p.name == "message")
    assert message_param.location == "body"
    assert message_param.required is True
    assert message_param.constraints.max_length == 200


def test_path_param_location() -> None:
    operations = parse_openapi(_SPEC_PATH.read_text())
    get_item = next(op for op in operations if op.operation_id == "getItem")
    item_id_param = next(p for p in get_item.params if p.name == "item_id")
    assert item_id_param.location == "path"
    assert item_id_param.kind is FieldKind.NUMBER


def test_to_form_model_produces_valid_form_model() -> None:
    operations = parse_openapi(_SPEC_PATH.read_text())
    search = next(op for op in operations if op.operation_id == "searchItems")
    form = search.to_form_model()
    assert form.group_id == "searchItems"
    assert {f.selector for f in form.fields} == {"query:q", "query:limit"}


def test_to_form_model_round_trips_through_fuzzer_strategies() -> None:
    """Regression guard (T13 acceptance): the existing fuzzer registry must generate
    FuzzCases against the converted FieldModels without modification."""
    from qai.engine.fuzzer.generator import DataGenerator

    operations = parse_openapi(_SPEC_PATH.read_text())
    search = next(op for op in operations if op.operation_id == "searchItems")
    form = search.to_form_model()
    plans = DataGenerator().plans(form)
    assert plans, "DataGenerator should produce fuzz plans for API-derived fields"


def test_malformed_json_raises_invalid_spec_error() -> None:
    with pytest.raises(InvalidSpecError):
        parse_openapi("not json and not yaml: {{{")


def test_missing_paths_raises_invalid_spec_error() -> None:
    with pytest.raises(InvalidSpecError):
        parse_openapi(json.dumps({"openapi": "3.0.3"}))
