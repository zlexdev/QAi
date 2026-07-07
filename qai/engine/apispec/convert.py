"""ApiOperation -> FormModel converter — the reuse seam (Decision B): once an
operation is a FormModel, the existing fuzzer/analyzer/direct_executor/reporter run
completely unmodified against it."""

from __future__ import annotations

from qai.engine.apispec.contracts import ApiOperation
from qai.engine.contracts import FieldModel, FormModel


def to_form_model(op: ApiOperation) -> FormModel:
    fields = [
        FieldModel(
            selector=f"{param.location}:{param.name}",
            name=param.name,
            kind=param.kind,
            group_id=op.operation_id,
            constraints=param.constraints,
        )
        for param in op.params
    ]
    return FormModel(
        group_id=op.operation_id,
        submit_selector=None,
        action=op.path,
        method=op.method,
        fields=fields,
    )
