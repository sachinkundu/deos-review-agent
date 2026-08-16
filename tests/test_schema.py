"""Deterministic tests for the review output schema and validation."""

from __future__ import annotations

import pytest

from review_bot.schema import SchemaError, load_schema, validate_review_output
from tests.conftest import make_finding, make_review


def test_load_schema_returns_contract():
    schema = load_schema()
    assert schema["additionalProperties"] is False
    assert "findings" in schema["properties"]
    # The agent driver requires strict schemas (codex --output-schema).
    assert schema["properties"]["overall_correctness"]["enum"] == [
        "patch is correct",
        "patch is incorrect",
    ]


def test_valid_output_passes():
    validate_review_output(make_review())
    validate_review_output(make_review(findings=[]))
    validate_review_output(make_review(findings=[make_finding(), make_finding(start=5, end=9)]))


def test_rejects_non_dict():
    with pytest.raises(SchemaError, match="expected an object"):
        validate_review_output(["not", "an", "object"])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("findings"),
        lambda d: d.pop("overall_correctness"),
        lambda d: d.pop("overall_explanation"),
        lambda d: d.pop("overall_confidence_score"),
        lambda d: d.pop("status"),
    ],
)
def test_rejects_missing_top_level_field(mutate):
    data = make_review()
    mutate(data)
    with pytest.raises(SchemaError):
        validate_review_output(data)


def test_rejects_extra_top_level_field():
    data = make_review()
    data["extra"] = 1
    with pytest.raises(SchemaError, match="Additional properties are not allowed"):
        validate_review_output(data)


def test_rejects_bad_priority():
    data = make_review(findings=[make_finding(priority=3)])
    with pytest.raises(SchemaError, match="priority"):
        validate_review_output(data)


def test_rejects_float_priority():
    data = make_review(findings=[make_finding(priority=1.5)])  # type: ignore[arg-type]
    with pytest.raises(SchemaError, match="priority"):
        validate_review_output(data)


def test_rejects_title_over_80_chars():
    data = make_review(findings=[make_finding(title="x" * 81)])
    with pytest.raises(SchemaError, match="maxLength"):
        validate_review_output(data)


def test_accepts_title_at_80_chars():
    validate_review_output(make_review(findings=[make_finding(title="x" * 80)]))


def test_rejects_bad_enums():
    data = make_review(overall_correctness="maybe")
    with pytest.raises(SchemaError, match="overall_correctness"):
        validate_review_output(data)
    data = make_review(status="done")
    with pytest.raises(SchemaError, match="status"):
        validate_review_output(data)


def test_rejects_confidence_out_of_range():
    data = make_review(overall_confidence_score=1.5)
    with pytest.raises(SchemaError, match="overall_confidence_score"):
        validate_review_output(data)
    data = make_review(findings=[make_finding(confidence=-0.1)])
    with pytest.raises(SchemaError, match="confidence_score"):
        validate_review_output(data)


def test_rejects_empty_title_and_body():
    data = make_review(findings=[make_finding(title="")])
    with pytest.raises(SchemaError):
        validate_review_output(data)
    data = make_review(findings=[make_finding(body="")])
    with pytest.raises(SchemaError):
        validate_review_output(data)


def test_rejects_missing_code_location_parts():
    finding = make_finding()
    del finding["code_location"]["line_range"]
    data = make_review(findings=[finding])
    with pytest.raises(SchemaError, match="line_range"):
        validate_review_output(data)


def test_rejects_zero_line_numbers():
    data = make_review(findings=[make_finding(start=0)])
    with pytest.raises(SchemaError, match="start"):
        validate_review_output(data)


def test_rejects_end_before_start():
    data = make_review(findings=[make_finding(start=10, end=5)])
    with pytest.raises(SchemaError, match="end \\(5\\) must be >= start \\(10\\)"):
        validate_review_output(data)


def test_error_messages_list_all_problems():
    data = make_review()
    del data["status"]
    data["findings"][0]["priority"] = 9
    with pytest.raises(SchemaError) as excinfo:
        validate_review_output(data)
    assert len(excinfo.value.errors) == 2


def test_suggested_fix_replacement_optional():
    finding = make_finding(replacement=None)
    validate_review_output(make_review(findings=[finding]))
