"""Load and validate review output against the shared review schema.

The review output schema is the shared contract between review agents, the
coordinator, and GitHub posting. Validation failures must be reported with
actionable error messages so the run can stop before any GitHub POST.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

import jsonschema

SCHEMA_PATH = Path(__file__).parent / "schema.json"
RECHECK_SCHEMA_PATH = Path(__file__).parent / "recheck_schema.json"
HISTORY_SCHEMA_PATH = Path(__file__).parent / "history_schema.json"
RECHECK_PLAN_SCHEMA_PATH = Path(__file__).parent / "recheck_plan_schema.json"


class SchemaError(Exception):
    """Raised when review output does not match the review output schema."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(
            "review output failed schema validation:\n" + "\n".join(f"- {e}" for e in errors)
        )


@lru_cache(maxsize=1)
def load_schema() -> dict:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=8)
def load_named_schema(path: str) -> dict:
    with open(Path(__file__).parent / path, encoding="utf-8") as f:
        return json.load(f)


def _format_location(error: jsonschema.ValidationError) -> str:
    where = ".".join(str(p) for p in error.absolute_path) or "<root>"
    keyword = error.validator
    if keyword:
        return f"{where}: {error.message} ({keyword})"
    return f"{where}: {error.message}"


def validate_review_output(data: object) -> None:
    """Validate a parsed review output object.

    Raises:
        SchemaError: with every validation problem, when ``data`` is not a dict
            or violates the review schema (including the line_range
            ``end >= start`` constraint, which JSON Schema cannot express).
    """
    if not isinstance(data, dict):
        raise SchemaError([f"<root>: expected an object, got {type(data).__name__}"])

    validator = jsonschema.Draft202012Validator(load_schema())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    problems = [_format_location(e) for e in errors]

    # Cross-field constraint: line_range.end must not precede line_range.start.
    for i, finding in enumerate(data.get("findings") or []):
        if not isinstance(finding, dict):
            continue
        location = finding.get("code_location")
        if not isinstance(location, dict):
            continue
        line_range = location.get("line_range")
        if isinstance(line_range, dict):
            start, end = line_range.get("start"), line_range.get("end")
            if isinstance(start, int) and isinstance(end, int) and end < start:
                msg = (
                    f"findings[{i}].code_location.line_range: "
                    f"end ({end}) must be >= start ({start})"
                )
                problems.append(msg)

    if problems:
        raise SchemaError(problems)


def validate_against_schema(data: object, schema: dict) -> None:
    """Validate an object against a strict JSON schema with stable diagnostics."""
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(cast(Any, data)), key=lambda e: list(e.absolute_path))
    problems = [_format_location(error) for error in errors]
    if problems:
        raise SchemaError(problems)


def validate_recheck_output(data: object) -> None:
    validate_against_schema(data, load_named_schema(RECHECK_SCHEMA_PATH.name))


def validate_history_snapshot(data: object) -> None:
    validate_against_schema(data, load_named_schema(HISTORY_SCHEMA_PATH.name))


def validate_recheck_plan(data: object) -> None:
    validate_against_schema(data, load_named_schema(RECHECK_PLAN_SCHEMA_PATH.name))
