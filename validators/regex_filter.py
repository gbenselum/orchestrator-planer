"""Deterministic regex filters and small-model output extractors."""

from __future__ import annotations

import re
from typing import Sequence

from validators.base import ValidationResult

FENCE_BLOCK_RE = re.compile(r"```(?:[a-zA-Z0-9_+-]+)?\s*\n(.*?)\n```", re.DOTALL)


def extract_fenced_or_raw(text: str) -> str:
    """Extract payload from markdown code fences if a 7B-9B worker included them."""
    stripped = text.strip()
    match = FENCE_BLOCK_RE.search(stripped)
    if match:
        return match.group(1)
    return stripped


def validate_regex_constraints(
    text: str,
    must_match: Sequence[str] = (),
    must_exclude: Sequence[str] = (),
) -> ValidationResult:
    """Deterministically verify that text matches required patterns and excludes forbidden ones."""
    errors: list[str] = []

    for pattern_str in must_match:
        try:
            pattern = re.compile(pattern_str, re.MULTILINE)
        except re.error as exc:
            errors.append(f"Invalid must_match regex {pattern_str!r}: {exc}")
            continue
        if not pattern.search(text):
            errors.append(f"Output did not match required regex pattern: {pattern_str!r}")

    for pattern_str in must_exclude:
        try:
            pattern = re.compile(pattern_str, re.MULTILINE)
        except re.error as exc:
            errors.append(f"Invalid must_exclude regex {pattern_str!r}: {exc}")
            continue
        if pattern.search(text):
            errors.append(f"Output matched forbidden regex pattern: {pattern_str!r}")

    return ValidationResult(
        passed=len(errors) == 0,
        validator_name="regex_filter",
        errors=errors,
    )
