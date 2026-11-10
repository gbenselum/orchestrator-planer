"""Deterministic Unified Diff Validator and Surgical Slice Patcher.

Enforces Context Minimization and Hermetic Contracts for `code_editor` tasks:
1. Verifies unified diff syntax and target file headers.
2. Enforces that all hunks stay strictly within `target_lines: [start_line, end_line]`.
3. Verifies that removed/context lines match the target file slice before mutation.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from validators.base import ValidationResult
from validators.regex_filter import extract_fenced_or_raw

HUNK_HEADER_RE = re.compile(
    r"^@@\s+-(\d+)(?:,(\d+))?\s+\+(\d+)(?:,(\d+))?\s+@@"
)


@dataclass
class DiffHunk:
    """Parsed unified diff hunk."""

    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]


def generate_unified_diff(
    target_file: str,
    target_lines: tuple[int, int],
    original_slice: str,
    replacement_slice: str,
) -> str:
    """Generate a canonical unified diff anchored at `target_lines`."""
    start_line, _ = target_lines
    orig_lines = original_slice.splitlines(keepends=True)
    repl_lines = replacement_slice.splitlines(keepends=True)
    if orig_lines and not orig_lines[-1].endswith("\n"):
        orig_lines[-1] += "\n"
    if repl_lines and not repl_lines[-1].endswith("\n"):
        repl_lines[-1] += "\n"

    raw_diff = list(
        difflib.unified_diff(
            orig_lines,
            repl_lines,
            fromfile=f"a/{target_file}",
            tofile=f"b/{target_file}",
            n=len(orig_lines) + len(repl_lines),
        )
    )
    if not raw_diff:
        return ""

    # Adjust hunk line numbers to reflect 1-based start_line in the full file
    adjusted: list[str] = []
    offset = start_line - 1
    for line in raw_diff:
        match = HUNK_HEADER_RE.match(line)
        if match:
            o_start = int(match.group(1)) + offset
            o_cnt = match.group(2)
            n_start = int(match.group(3)) + offset
            n_cnt = match.group(4)
            o_part = f"-{o_start},{o_cnt}" if o_cnt is not None else f"-{o_start}"
            n_part = f"+{n_start},{n_cnt}" if n_cnt is not None else f"+{n_start}"
            adjusted.append(f"@@ {o_part} {n_part} @@\n")
        else:
            adjusted.append(line)
    return "".join(adjusted)


def parse_unified_diff(diff_text: str) -> tuple[str | None, str | None, list[DiffHunk], list[str]]:
    """Parse a unified diff into (from_file, to_file, hunks, parse_errors)."""
    cleaned = extract_fenced_or_raw(diff_text)
    lines = cleaned.splitlines()
    from_file: str | None = None
    to_file: str | None = None
    hunks: list[DiffHunk] = []
    errors: list[str] = []

    current_hunk: DiffHunk | None = None
    for idx, line in enumerate(lines, start=1):
        if line.startswith("--- ") and current_hunk is None:
            from_file = line[4:].strip().split("\t")[0]
            if from_file.startswith("a/"):
                from_file = from_file[2:]
        elif line.startswith("+++ ") and current_hunk is None:
            to_file = line[4:].strip().split("\t")[0]
            if to_file.startswith("b/"):
                to_file = to_file[2:]
        elif line.startswith("@@"):
            match = HUNK_HEADER_RE.match(line)
            if not match:
                errors.append(f"Malformed hunk header at diff line {idx}: {line!r}")
                continue
            old_start = int(match.group(1))
            old_count = int(match.group(2)) if match.group(2) is not None else 1
            new_start = int(match.group(3))
            new_count = int(match.group(4)) if match.group(4) is not None else 1
            current_hunk = DiffHunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=[],
            )
            hunks.append(current_hunk)
        elif current_hunk is not None:
            if line.startswith(("+", "-", " ")):
                current_hunk.lines.append(line)
            elif line.startswith("\\ No newline at end of file"):
                continue
            elif line == "":
                # Treat bare empty line inside hunk as an empty context line
                current_hunk.lines.append(" ")
            else:
                errors.append(f"Unexpected line prefix inside hunk at diff line {idx}: {line!r}")

    if not hunks and not errors:
        errors.append("Diff contains no valid '@@ ... @@' hunks")

    return from_file, to_file, hunks, errors


def validate_and_apply_diff(
    diff_text: str,
    target_file: str,
    target_lines: tuple[int, int],
    full_file_content: str,
) -> ValidationResult:
    """Validate a unified diff against target bounds and compute the patched file content."""
    from_file, to_file, hunks, parse_errors = parse_unified_diff(diff_text)
    if parse_errors:
        return ValidationResult(
            passed=False,
            validator_name="diff_validator",
            errors=parse_errors,
        )

    errors: list[str] = []
    for header_file in (from_file, to_file):
        if header_file is not None and header_file != target_file:
            errors.append(
                f"Diff header target '{header_file}' does not match authorized target_file '{target_file}'"
            )

    start_bound, end_bound = target_lines
    file_lines = full_file_content.splitlines()

    if start_bound < 1 or end_bound > max(len(file_lines), end_bound):
        errors.append(
            f"target_lines [{start_bound}, {end_bound}] out of bounds for file with {len(file_lines)} lines"
        )

    # Check each hunk's line bounds and context match
    patched_lines = list(file_lines)
    # Apply hunks in reverse order if multiple, after verifying ascending non-overlapping order
    last_end = 0
    for hunk in hunks:
        hunk_old_lines = [hl[1:] for hl in hunk.lines if hl.startswith((" ", "-"))]
        actual_old_count = len(hunk_old_lines)
        if actual_old_count != hunk.old_count and hunk.old_count != 1:
            errors.append(
                f"Hunk @@ -{hunk.old_start},{hunk.old_count} @@ declared {hunk.old_count} old lines "
                f"but body has {actual_old_count}"
            )

        # Allow relative (1-based within slice) or absolute (1-based within file) hunk numbering
        effective_start = hunk.old_start
        if effective_start == 1 and start_bound > 1:
            # Check if relative numbering matches the slice at start_bound
            candidate_slice = file_lines[start_bound - 1 : start_bound - 1 + actual_old_count]
            if _lines_match(candidate_slice, hunk_old_lines):
                effective_start = start_bound

        effective_end = effective_start + actual_old_count - 1
        if effective_start < start_bound or effective_end > end_bound:
            # Try locating exact match within [start_bound, end_bound] if line number drifted slightly
            located_start = _find_subsequence_in_bounds(
                file_lines, hunk_old_lines, start_bound, end_bound
            )
            if located_start is not None:
                effective_start = located_start
                effective_end = effective_start + actual_old_count - 1
            else:
                errors.append(
                    f"Hunk lines [{effective_start}, {effective_end}] violate authorized "
                    f"target_lines boundary [{start_bound}, {end_bound}]"
                )
                continue

        if effective_start <= last_end:
            errors.append("Overlapping or out-of-order diff hunks detected")
            continue
        last_end = effective_end

        target_slice = file_lines[effective_start - 1 : effective_end]
        if not _lines_match(target_slice, hunk_old_lines):
            errors.append(
                f"Hunk context/removal lines at lines [{effective_start}, {effective_end}] "
                f"do not match file content"
            )
        # Store resolved 1-based start on hunk for deterministic application
        hunk.old_start = effective_start

    if errors:
        return ValidationResult(
            passed=False,
            validator_name="diff_validator",
            errors=errors,
        )

    # Apply hunks in reverse line order to preserve indices
    for hunk in reversed(hunks):
        hunk_old_lines = [hl[1:] for hl in hunk.lines if hl.startswith((" ", "-"))]
        # Determine indentation offset if hunk was unindented relative to file slice
        orig_slice = patched_lines[hunk.old_start - 1 : hunk.old_start - 1 + len(hunk_old_lines)]
        indent_prefix = _detect_shared_indent_offset(orig_slice, hunk_old_lines)
        new_lines_for_hunk: list[str] = []
        for hl in hunk.lines:
            if hl.startswith((" ", "+")):
                content_line = hl[1:]
                if indent_prefix and content_line.strip():
                    content_line = indent_prefix + content_line
                new_lines_for_hunk.append(content_line)
        patched_lines[hunk.old_start - 1 : hunk.old_start - 1 + len(hunk_old_lines)] = (
            new_lines_for_hunk
        )

    trailing_newline = "\n" if full_file_content.endswith("\n") or not full_file_content else ""
    patched_content = "\n".join(patched_lines) + trailing_newline

    return ValidationResult(
        passed=True,
        validator_name="diff_validator",
        errors=[],
        metadata={
            "patched_content": patched_content,
            "hunks_applied": len(hunks),
        },
    )


def _lines_match(actual_lines: list[str], expected_lines: list[str]) -> bool:
    if len(actual_lines) != len(expected_lines):
        return False
    if actual_lines == expected_lines:
        return True
    # Also allow match when context_snippet in YAML was dedented uniformly relative to the file slice
    prefix = _detect_shared_indent_offset(actual_lines, expected_lines)
    if prefix is not None:
        return all(
            a == (prefix + e if e.strip() else a)
            for a, e in zip(actual_lines, expected_lines)
        )
    return False


def _detect_shared_indent_offset(actual_lines: list[str], expected_lines: list[str]) -> str | None:
    if len(actual_lines) != len(expected_lines):
        return None
    prefixes: set[str] = set()
    for act, exp in zip(actual_lines, expected_lines):
        if not exp.strip() and not act.strip():
            continue
        if act == exp:
            prefixes.add("")
        elif act.endswith(exp) and act[: len(act) - len(exp)].strip() == "":
            prefixes.add(act[: len(act) - len(exp)])
        else:
            return None
    if len(prefixes) == 1:
        return next(iter(prefixes))
    return None


def _find_subsequence_in_bounds(
    file_lines: list[str],
    hunk_old_lines: list[str],
    start_bound: int,
    end_bound: int,
) -> int | None:
    n_hunk = len(hunk_old_lines)
    if n_hunk == 0:
        return None
    max_start = min(len(file_lines) - n_hunk + 1, end_bound - n_hunk + 1)
    for pos in range(max(1, start_bound), max_start + 1):
        candidate = file_lines[pos - 1 : pos - 1 + n_hunk]
        if _lines_match(candidate, hunk_old_lines):
            return pos
    return None
