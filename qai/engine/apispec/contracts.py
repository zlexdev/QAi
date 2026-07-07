"""apispec contracts — OpenAPI/GraphQL operations converted to the EXISTING
FormModel/FieldModel vocabulary (Decision B, plan `00-decisions.md`), so the fuzzer/
analyzer/direct_executor/reporter run completely unmodified against API-scanned
operations."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

from qai.engine.contracts import (
    _FROZEN,
    FieldConstraints,
    FieldKind,
    FormModel,
    HttpMethod,
)


class ApiSpecKind(StrEnum):
    OPENAPI = "openapi"
    GRAPHQL = "graphql"


class ApiParam(BaseModel):
    model_config = _FROZEN
    name: str
    kind: FieldKind
    required: bool = False
    constraints: FieldConstraints = Field(default_factory=FieldConstraints)
    location: Literal["path", "query", "body", "arg"] = "query"


class ApiOperation(BaseModel):
    model_config = _FROZEN
    operation_id: str
    method: HttpMethod
    path: str
    params: list[ApiParam] = Field(default_factory=list)
    source: ApiSpecKind

    def to_form_model(self) -> FormModel:
        """The reuse seam — converts to the EXISTING FormModel/FieldModel vocabulary.
        A param's ``selector`` is a synthetic ``"<location>:<name>"`` token (there's no
        DOM element to select against an API operation) — the fuzzer/executor only
        ever use ``selector`` as an opaque dict key, never as a real CSS selector, so
        this is a safe reuse of the field."""
        from qai.engine.apispec.convert import to_form_model

        return to_form_model(self)


class ApiSpecSource(BaseModel):
    model_config = _FROZEN
    kind: ApiSpecKind
    raw: str
