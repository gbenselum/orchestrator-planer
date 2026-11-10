"""Deterministic assertion modules (CLI checkers, unified diff validators, JSON schema validators, regex filters)."""

from validators.base import ValidationResult
from validators.cli_checker import validate_cli_outcome
from validators.diff_validator import (
    DiffHunk,
    generate_unified_diff,
    parse_unified_diff,
    validate_and_apply_diff,
)
from validators.regex_filter import extract_fenced_or_raw, validate_regex_constraints
from validators.schema_validator import validate_json_schema

__all__ = [
    "DiffHunk",
    "ValidationResult",
    "extract_fenced_or_raw",
    "generate_unified_diff",
    "parse_unified_diff",
    "validate_and_apply_diff",
    "validate_cli_outcome",
    "validate_json_schema",
    "validate_regex_constraints",
]
