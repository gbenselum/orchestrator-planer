"""Decomposition Rules & Zero-Inference Test Validator.

Enforces Section 1 (Zero-Inference Execution) and Section 2 (Core Constraints &
Guiding Principles) of the Architecture Spec before any task is dispatched to a
7B-9B subagent worker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePath

from planner.schema import ExecutionPlan, SubagentRole, TaskSpec

# Patterns that indicate open-ended reasoning, multi-turn memory assumptions,
# or conditional branching pushed inside a worker instruction (violating
# Zero-Inference Execution and Decoupled Orchestration).
AMBIGUOUS_INSTRUCTION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\b(figure out|investigate|explore the codebase|find out why|search for where)\b", re.I),
        "Instruction requires open-ended exploration instead of zero-inference execution",
    ),
    (
        re.compile(r"\b(decide whether|choose the best|use your judgment|if you think)\b", re.I),
        "Instruction delegates architectural/branching judgment to a 7B-9B worker",
    ),
    (
        re.compile(r"\b(as discussed earlier|from our previous turn|remember from earlier|in the last step)\b", re.I),
        "Instruction assumes multi-turn conversational state across ephemeral sessions",
    ),
    (
        re.compile(r"\b(if the tests? fail|if that doesn't work,?\s+then)\b", re.I),
        "Instruction embeds conditional branching logic that belongs in the Orchestrator",
    ),
)

HYDRATION_REF_PATTERN = re.compile(r"\{\{\s*tasks\.([a-zA-Z0-9_-]+)\.([a-zA-Z0-9_.-]+)\s*\}\}")


@dataclass
class ZeroInferenceConfig:
    """Configurable thresholds for the Zero-Inference Linter."""

    max_target_line_span: int = 150
    max_context_snippet_chars: int = 6000
    max_instruction_chars: int = 600
    disallow_shell_chaining_in_validator: bool = True


@dataclass
class ZeroInferenceReport:
    """Deterministic report emitted by the Zero-Inference Test."""

    passed: bool
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_zero_inference_task(
    task: TaskSpec,
    preceding_task_ids: set[str],
    config: ZeroInferenceConfig | None = None,
) -> list[str]:
    """Validate a single TaskSpec against Zero-Inference Execution constraints."""
    cfg = config or ZeroInferenceConfig()
    violations: list[str] = []

    # 1. Instruction conciseness & zero-inference check
    if len(task.instruction) > cfg.max_instruction_chars:
        violations.append(
            f"Task '{task.task_id}': instruction length ({len(task.instruction)} chars) "
            f"exceeds max_instruction_chars ({cfg.max_instruction_chars})"
        )

    for pattern, reason in AMBIGUOUS_INSTRUCTION_PATTERNS:
        if pattern.search(task.instruction):
            violations.append(f"Task '{task.task_id}': {reason} ('{task.instruction}')")

    # 2. Context Minimization for code_editor
    if task.subagent == SubagentRole.CODE_EDITOR:
        if task.target_file:
            path_parts = PurePath(task.target_file).parts
            if ".." in path_parts or task.target_file.startswith("/"):
                violations.append(
                    f"Task '{task.task_id}': target_file '{task.target_file}' must be a "
                    f"workspace-relative path without '..'"
                )
        if task.target_lines is not None:
            start, end = task.target_lines
            span = end - start + 1
            if span > cfg.max_target_line_span:
                violations.append(
                    f"Task '{task.task_id}': target_lines span ({span} lines) exceeds "
                    f"context minimization bound ({cfg.max_target_line_span} lines)"
                )
        if task.context_snippet and len(task.context_snippet) > cfg.max_context_snippet_chars:
            violations.append(
                f"Task '{task.task_id}': context_snippet ({len(task.context_snippet)} chars) "
                f"exceeds max_context_snippet_chars ({cfg.max_context_snippet_chars})"
            )

    # 3. Read-only safety for validator subagent
    if task.subagent == SubagentRole.VALIDATOR and task.command:
        if cfg.disallow_shell_chaining_in_validator and any(
            op in task.command for op in ("&&", "||", ";", ">", "|")
        ):
            violations.append(
                f"Task '{task.task_id}': validator command '{task.command}' must be a single "
                f"read-only check command without shell chaining or redirection"
            )

    # 4. Dependency & Hydration Reference Validation
    for dep_id in task.depends_on:
        if dep_id not in preceding_task_ids:
            violations.append(
                f"Task '{task.task_id}': depends_on reference '{dep_id}' does not refer to an "
                f"earlier task in topological order"
            )

    # Check hydration placeholders in command, context_snippet, replacement_payload, and inputs
    searchable_strings: list[str] = []
    if task.command:
        searchable_strings.append(task.command)
    if task.context_snippet:
        searchable_strings.append(task.context_snippet)
    if task.replacement_payload:
        searchable_strings.append(task.replacement_payload)
    for val in task.inputs.values():
        if isinstance(val, str):
            searchable_strings.append(val)

    for text in searchable_strings:
        for match in HYDRATION_REF_PATTERN.finditer(text):
            ref_task_id = match.group(1)
            if ref_task_id not in preceding_task_ids:
                violations.append(
                    f"Task '{task.task_id}': hydration reference '{{{{tasks.{ref_task_id}...}}}}' "
                    f"must reference a preceding task (available: {sorted(preceding_task_ids)})"
                )

    return violations


def run_zero_inference_check(
    plan: ExecutionPlan,
    config: ZeroInferenceConfig | None = None,
) -> ZeroInferenceReport:
    """Run the full Zero-Inference Test across all tasks in an ExecutionPlan."""
    cfg = config or ZeroInferenceConfig()
    all_violations: list[str] = []
    warnings: list[str] = []
    preceding_ids: set[str] = set()

    for task in plan.tasks:
        task_violations = validate_zero_inference_task(task, preceding_ids, cfg)
        all_violations.extend(task_violations)
        preceding_ids.add(task.task_id)

    return ZeroInferenceReport(
        passed=len(all_violations) == 0,
        violations=all_violations,
        warnings=warnings,
    )
