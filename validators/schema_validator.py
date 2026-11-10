"""Deterministic JSON Schema validator for parser/transformer subagent outputs."""

from __future__ import annotations

import json
import re
from typing import Any

from validators.base import ValidationResult
from validators.regex_filter import extract_fenced_or_raw


def validate_json_schema(raw_output: str | Any, schema: dict[str, Any]) -> ValidationResult:
    """Parse JSON (if string) and validate deterministically against a JSON Schema subset."""
    errors: list[str] = []
    parsed: Any

    if isinstance(raw_output, str):
        cleaned = extract_fenced_or_raw(raw_output)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            return ValidationResult(
                passed=False,
                validator_name="schema_validator",
                errors=[f"Invalid JSON syntax at line {exc.lineno} col {exc.colno}: {exc.msg}"],
            )
    else:
        parsed = raw_output

    _validate_node(parsed, schema, path="$", errors=errors)
    return ValidationResult(
        passed=len(errors) == 0,
        validator_name="schema_validator",
        errors=errors,
        metadata={"parsed_json": parsed if len(errors) == 0 else None},
    )


def _check_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _validate_node(value: Any, schema: dict[str, Any], path: str, errors: list[str]) -> None:
    expected_type = schema.get("type")
    if expected_type is not None:
        if isinstance(expected_type, list):
            if not any(_check_type(value, t) for t in expected_type):
                errors.append(
                    f"{path}: expected type in {expected_type}, got {type(value).__name__}"
                )
                return
        elif not _check_type(value, expected_type):
            errors.append(
                f"{path}: expected type '{expected_type}', got '{type(value).__name__}'"
            )
            return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} not in allowed enum {schema['enum']}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            errors.append(f"{path}: string length {len(value)} < minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path}: string length {len(value)} > maxLength {schema['maxLength']}")
        if "pattern" in schema:
            if not re.search(schema["pattern"], value):
                errors.append(f"{path}: string {value!r} does not match pattern {schema['pattern']!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: value {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: value {value} > maximum {schema['maximum']}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for req_key in required:
            if req_key not in value:
                errors.append(f"{path}: missing required property '{req_key}'")

        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for k, v in value.items():
            child_path = f"{path}.{k}"
            if k in properties:
                _validate_node(v, properties[k], child_path, errors)
            elif additional is False:
                errors.append(f"{path}: unexpected additional property '{k}'")
            elif isinstance(additional, dict):
                _validate_node(v, additional, child_path, errors)

    if isinstance(value, list):
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            errors.append(f"{path}: array length {len(value)} < minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path}: array length {len(value)} > maxItems {schema['maxItems']}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for idx, item in enumerate(value):
                _validate_node(item, item_schema, f"{path}[{idx}]", errors)
