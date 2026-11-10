"""Deterministic CLI status, exit code, and output assertion module."""

from __future__ import annotations

from planner.schema import ExpectedOutcome
from validators.base import ValidationResult
from validators.regex_filter import validate_regex_constraints


def validate_cli_outcome(
    exit_code: int,
    stdout: str,
    stderr: str,
    expected: ExpectedOutcome | None,
    timed_out: bool = False,
) -> ValidationResult:
    """Validate CLI execution results against an ExpectedOutcome contract."""
    errors: list[str] = []

    if timed_out:
        errors.append("Command execution timed out before completion")

    if expected is None:
        if exit_code != 0 and not timed_out:
            errors.append(f"Expected default exit_code 0, got {exit_code}")
        return ValidationResult(
            passed=len(errors) == 0,
            validator_name="cli_checker",
            errors=errors,
            metadata={"exit_code": exit_code},
        )

    if expected.exit_code is not None and exit_code != expected.exit_code:
        errors.append(f"Expected exit_code {expected.exit_code}, got {exit_code}")

    for snippet in expected.stdout_contains:
        if snippet not in stdout:
            errors.append(f"stdout missing required substring: {snippet!r}")

    for snippet in expected.stderr_contains:
        if snippet not in stderr:
            errors.append(f"stderr missing required substring: {snippet!r}")

    combined_output = f"{stdout}\n{stderr}"
    if expected.regex_matches or expected.regex_excludes:
        regex_res = validate_regex_constraints(
            text=combined_output,
            must_match=expected.regex_matches,
            must_exclude=expected.regex_excludes,
        )
        if not regex_res.passed:
            errors.extend(regex_res.errors)

    if expected.passed is not None:
        actual_bool = (exit_code == (expected.exit_code if expected.exit_code is not None else 0)) and (
            len(errors) == 0
        )
        if actual_bool != expected.passed:
            errors.append(f"Expected boolean pass status {expected.passed}, got {actual_bool}")

    return ValidationResult(
        passed=len(errors) == 0,
        validator_name="cli_checker",
        errors=errors,
        metadata={
            "exit_code": exit_code,
            "timed_out": timed_out,
        },
    )
