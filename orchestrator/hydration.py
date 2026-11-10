"""Context Minimization Slicer & Deterministic Task Input Hydrator.

Enforces Section 2 (Context Minimization) and Section 5 (Pass: Hydrate
downstream task with result; proceed to next step) of the Architecture Spec.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.state import TaskExecutionRecord
from planner.rules import HYDRATION_REF_PATTERN
from planner.schema import TaskSpec


class ContextHydrationError(RuntimeError):
    """Raised when file slicing or upstream output hydration fails."""


def resolve_confined_path(workspace_root: Path, relative_file: str) -> Path:
    """Resolve `relative_file` strictly inside `workspace_root`."""
    root_resolved = workspace_root.resolve()
    candidate = (root_resolved / relative_file).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise ContextHydrationError(
            f"Path '{relative_file}' escapes workspace root '{root_resolved}'"
        ) from exc
    return candidate


def extract_file_slice(
    workspace_root: Path,
    target_file: str,
    target_lines: tuple[int, int] | None = None,
) -> tuple[str, str]:
    """Read `target_file` and return `(full_content, bounded_slice_content)`."""
    file_path = resolve_confined_path(workspace_root, target_file)
    if not file_path.exists():
        raise ContextHydrationError(f"Target file does not exist: '{target_file}'")

    full_content = file_path.read_text(encoding="utf-8")
    if target_lines is None:
        return full_content, full_content

    start_line, end_line = target_lines
    lines = full_content.splitlines()
    if start_line < 1 or start_line > max(len(lines), 1):
        raise ContextHydrationError(
            f"target_lines [{start_line}, {end_line}] start_line out of range "
            f"for '{target_file}' ({len(lines)} lines)"
        )

    bounded_lines = lines[start_line - 1 : end_line]
    slice_content = "\n".join(bounded_lines) + ("\n" if bounded_lines else "")
    return full_content, slice_content


def hydrate_template_string(
    template: str,
    completed_records: dict[str, TaskExecutionRecord],
) -> str:
    """Replace `{{tasks.<id>.<field>}}` expressions with deterministic upstream outputs."""

    def _replacer(match: Any) -> str:
        ref_task_id = match.group(1)
        field_path = match.group(2)
        if ref_task_id not in completed_records:
            raise ContextHydrationError(
                f"Cannot hydrate reference to uncompleted task '{ref_task_id}'"
            )
        record = completed_records[ref_task_id]
        val = _resolve_record_field(record, field_path)
        return str(val)

    return HYDRATION_REF_PATTERN.sub(_replacer, template)


def _resolve_record_field(record: TaskExecutionRecord, field_path: str) -> Any:
    parts = field_path.split(".")
    head = parts[0]
    if head == "stdout":
        return (record.output.stdout if record.output else "").rstrip("\n")
    if head == "stderr":
        return (record.output.stderr if record.output else "").rstrip("\n")
    if head == "exit_code":
        return record.output.exit_code if record.output else None
    if head == "raw_output":
        return (record.output.raw_output if record.output else "").rstrip("\n")
    if head == "parsed_json":
        cur: Any = record.parsed_json
        for part in parts[1:]:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                raise ContextHydrationError(
                    f"Task '{record.task_id}' parsed_json has no field '{field_path}'"
                )
        return cur
    raise ContextHydrationError(
        f"Unsupported hydration field '{field_path}' on task '{record.task_id}'"
    )


def hydrate_value(
    value: Any,
    completed_records: dict[str, TaskExecutionRecord],
) -> Any:
    """Recursively hydrate strings, dicts, and lists."""
    if isinstance(value, str):
        return hydrate_template_string(value, completed_records)
    if isinstance(value, dict):
        return {k: hydrate_value(v, completed_records) for k, v in value.items()}
    if isinstance(value, list):
        return [hydrate_value(item, completed_records) for item in value]
    return value


def hydrate_task_inputs(
    task: TaskSpec,
    completed_records: dict[str, TaskExecutionRecord],
    workspace_root: Path,
) -> dict[str, Any]:
    """Build the strictly bounded isolated input dictionary for a single task."""
    isolated: dict[str, Any] = {}

    if task.command is not None:
        isolated["command"] = hydrate_template_string(task.command, completed_records)

    if task.inputs:
        isolated["inputs"] = hydrate_value(task.inputs, completed_records)

    if task.context_snippet is not None:
        isolated["context_snippet"] = hydrate_template_string(
            task.context_snippet, completed_records
        )

    if task.replacement_payload is not None:
        isolated["replacement_payload"] = hydrate_template_string(
            task.replacement_payload, completed_records
        )

    if task.target_file is not None:
        full_content, file_slice = extract_file_slice(
            workspace_root=workspace_root,
            target_file=task.target_file,
            target_lines=task.target_lines,
        )
        isolated["full_file_content"] = full_content
        isolated["file_slice"] = file_slice

    return isolated
