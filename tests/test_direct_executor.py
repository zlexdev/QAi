from __future__ import annotations

from qai.engine.contracts import (
    CapturedRequest,
    FieldConstraints,
    FieldKind,
    FieldModel,
    FormModel,
    HttpMethod,
    ResponseKind,
)
from qai.engine.direct_executor import learn_template


def _field(name: str, selector: str) -> FieldModel:
    return FieldModel(
        selector=selector,
        name=name,
        kind=FieldKind.TEXT,
        group_id="g1",
        constraints=FieldConstraints(),
    )


def _form(fields: list[FieldModel]) -> FormModel:
    return FormModel(group_id="signup-form", submit_selector="#submit", fields=fields)


def test_learn_template_succeeds_for_simple_form_urlencoded_body() -> None:
    form = _form([_field("name", "#name"), _field("email", "#email")])
    baseline = CapturedRequest(
        method=HttpMethod.POST,
        url="http://x/signup",
        status=200,
        response_kind=ResponseKind.OK,
        request_body="name=Alice&email=alice%40example.com",
        content_type="application/x-www-form-urlencoded",
    )
    template = learn_template(form, baseline)
    assert template is not None
    assert template.field_values["#name"] == "Alice"
    assert template.field_values["#email"] == "alice@example.com"


def test_learn_template_rejects_non_form_urlencoded_content_type() -> None:
    form = _form([_field("name", "#name")])
    baseline = CapturedRequest(
        method=HttpMethod.POST,
        url="http://x/signup",
        status=200,
        response_kind=ResponseKind.OK,
        request_body='{"name": "Alice"}',
        content_type="application/json",
    )
    assert learn_template(form, baseline) is None


def test_learn_template_rejects_duplicate_values() -> None:
    # Both fields share the value "same" -> substitution would be ambiguous.
    form = _form([_field("name", "#name"), _field("nickname", "#nickname")])
    baseline = CapturedRequest(
        method=HttpMethod.POST,
        url="http://x/signup",
        status=200,
        response_kind=ResponseKind.OK,
        request_body="name=same&nickname=same",
        content_type="application/x-www-form-urlencoded",
    )
    assert learn_template(form, baseline) is None


def test_learn_template_rejects_missing_field() -> None:
    # "csrf_token" in the body isn't traceable to any form field -> not attempted,
    # but a field the form DOES have that's missing from the body must fail closed.
    form = _form([_field("name", "#name"), _field("email", "#email")])
    baseline = CapturedRequest(
        method=HttpMethod.POST,
        url="http://x/signup",
        status=200,
        response_kind=ResponseKind.OK,
        request_body="name=Alice",
        content_type="application/x-www-form-urlencoded",
    )
    assert learn_template(form, baseline) is None
