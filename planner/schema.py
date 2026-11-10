"""Standardized Execution Contract & Planner Output Schema.

Implements Section 3 (Subagent Taxonomy) and Section 4 (Planner Output Schema)
of the Architecture Spec. Supports both Pydantic v2 (when installed) and
strict deterministic stdlib validation so any harness can run immediately.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from planner.compat import dump_yaml, load_yaml


class PlanValidationError(ValueError):
    """Raised when a plan or task violates the standardized execution schema."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message)
        self.errors: list[str] = errors or [message]


class SubagentRole(str, Enum):
    """Subagent taxonomy defined in Section 3 of the Architecture Spec & DevOps extensions."""

    CODE_EDITOR = "code_editor"
    COMMAND_RUNNER = "command_runner"
    PARSER = "parser"
    TRANSFORMER = "transformer"
    VALIDATOR = "validator"
    KUBECTL = "kubectl"
    DOCKER = "docker"
    GH = "gh"

    @classmethod
    def normalize(cls, val: str | SubagentRole) -> SubagentRole:
        """Normalize role names and common aliases (e.g., 'kubectl_runner' -> 'kubectl')."""
        if isinstance(val, cls):
            return val
        s = str(val).strip().lower()
        alias_map = {
            "kubectl_runner": cls.KUBECTL,
            "kubectl": cls.KUBECTL,
            "docker_runner": cls.DOCKER,
            "docker": cls.DOCKER,
            "gh_runner": cls.GH,
            "gh": cls.GH,
        }
        if s in alias_map:
            return alias_map[s]
        return cls(s)


class ExpectedFormat(str, Enum):
    """Expected output format for generative subagents."""

    UNIFIED_DIFF = "unified_diff"
    EXACT_SLICE = "exact_slice"
    JSON = "json"
    BOOLEAN_REPORT = "boolean_report"


class FailurePolicy(str, Enum):
    """Deterministic failure routing policies handled by the Orchestrator."""

    ABORT_TO_PLANNER = "abort_to_planner"
    RETRY_WITH_DIFF_VALIDATION = "retry_with_diff_validation"
    RETRY_WITH_SCHEMA_VALIDATION = "retry_with_schema_validation"
    ROUTE_TO_PLANNER_FOR_REPLAN = "route_to_planner_for_replan"
    HALT = "halt"


@dataclass
class ExpectedOutcome:
    """Deterministic verification criteria for command_runner and validator tasks."""

    exit_code: int | None = None
    stdout_contains: list[str] = field(default_factory=list)
    stderr_contains: list[str] = field(default_factory=list)
    regex_matches: list[str] = field(default_factory=list)
    regex_excludes: list[str] = field(default_factory=list)
    passed: bool | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ExpectedOutcome | None:
        if data is None:
            return None
        if not isinstance(data, dict):
            raise PlanValidationError(f"expected_outcome must be a mapping, got {type(data).__name__}")
        exit_code = data.get("exit_code")
        if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
            raise PlanValidationError("expected_outcome.exit_code must be an integer")
        passed = data.get("passed")
        if passed is not None and not isinstance(passed, bool):
            raise PlanValidationError("expected_outcome.passed must be a boolean")
        return cls(
            exit_code=exit_code,
            stdout_contains=list(data.get("stdout_contains", [])),
            stderr_contains=list(data.get("stderr_contains", [])),
            regex_matches=list(data.get("regex_matches", [])),
            regex_excludes=list(data.get("regex_excludes", [])),
            passed=passed,
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.exit_code is not None:
            out["exit_code"] = self.exit_code
        if self.stdout_contains:
            out["stdout_contains"] = list(self.stdout_contains)
        if self.stderr_contains:
            out["stderr_contains"] = list(self.stderr_contains)
        if self.regex_matches:
            out["regex_matches"] = list(self.regex_matches)
        if self.regex_excludes:
            out["regex_excludes"] = list(self.regex_excludes)
        if self.passed is not None:
            out["passed"] = self.passed
        return out


@dataclass
class TaskSpec:
    """Hermetic, atomic micro-task specification."""

    task_id: str
    subagent: SubagentRole
    instruction: str
    on_failure: FailurePolicy
    command: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    target_file: str | None = None
    target_lines: tuple[int, int] | None = None
    context_snippet: str | None = None
    replacement_payload: str | None = None
    expected_format: ExpectedFormat | None = None
    output_schema: dict[str, Any] | None = None
    expected_outcome: ExpectedOutcome | None = None
    depends_on: list[str] = field(default_factory=list)
    max_retries: int = 2
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        self.validate_schema()

    def validate_schema(self) -> None:
        errors: list[str] = []
        if not self.task_id or not isinstance(self.task_id, str) or not self.task_id.strip():
            errors.append("task_id must be a non-empty string")
        if not self.instruction or not isinstance(self.instruction, str) or not self.instruction.strip():
            errors.append(f"Task '{self.task_id}': instruction must be a non-empty string")

        try:
            self.subagent = SubagentRole.normalize(self.subagent)
        except (ValueError, KeyError):
            valid = [r.value for r in SubagentRole]
            errors.append(
                f"Task '{self.task_id}': invalid subagent '{self.subagent}'. Must be one of {valid}"
            )

        try:
            self.on_failure = FailurePolicy(self.on_failure)
        except ValueError:
            valid_fp = [f.value for f in FailurePolicy]
            errors.append(
                f"Task '{self.task_id}': invalid on_failure '{self.on_failure}'. Must be one of {valid_fp}"
            )

        if self.expected_format is not None:
            try:
                self.expected_format = ExpectedFormat(self.expected_format)
            except ValueError:
                valid_fmt = [f.value for f in ExpectedFormat]
                errors.append(
                    f"Task '{self.task_id}': invalid expected_format '{self.expected_format}'. "
                    f"Must be one of {valid_fmt}"
                )

        if self.target_lines is not None:
            if (
                not isinstance(self.target_lines, (list, tuple))
                or len(self.target_lines) != 2
                or not all(isinstance(x, int) and not isinstance(x, bool) for x in self.target_lines)
            ):
                errors.append(
                    f"Task '{self.task_id}': target_lines must be a [start_line, end_line] integer pair"
                )
            else:
                start, end = int(self.target_lines[0]), int(self.target_lines[1])
                if start < 1 or end < start:
                    errors.append(
                        f"Task '{self.task_id}': target_lines [{start}, {end}] must have 1 <= start <= end"
                    )
                self.target_lines = (start, end)

        # Role-specific contract validation
        if isinstance(self.subagent, SubagentRole):
            if self.subagent == SubagentRole.COMMAND_RUNNER:
                if not self.command or not self.command.strip():
                    errors.append(f"Task '{self.task_id}' (command_runner) requires a 'command' string")
                if self.expected_outcome is None:
                    errors.append(
                        f"Task '{self.task_id}' (command_runner) requires an 'expected_outcome' block"
                    )
            elif self.subagent == SubagentRole.CODE_EDITOR:
                if not self.target_file:
                    errors.append(f"Task '{self.task_id}' (code_editor) requires 'target_file'")
                if self.target_lines is None:
                    errors.append(
                        f"Task '{self.task_id}' (code_editor) requires 'target_lines: [start, end]'"
                    )
                if self.context_snippet is None:
                    errors.append(f"Task '{self.task_id}' (code_editor) requires 'context_snippet'")
                if self.replacement_payload is None:
                    errors.append(f"Task '{self.task_id}' (code_editor) requires 'replacement_payload'")
                if self.expected_format is None:
                    self.expected_format = ExpectedFormat.UNIFIED_DIFF
            elif self.subagent in (SubagentRole.PARSER, SubagentRole.TRANSFORMER):
                if not self.output_schema or not isinstance(self.output_schema, dict):
                    errors.append(
                        f"Task '{self.task_id}' ({self.subagent.value}) requires 'output_schema' dict"
                    )
                if self.command is not None:
                    errors.append(
                        f"Task '{self.task_id}' ({self.subagent.value}) has zero tools and cannot specify 'command'"
                    )
            elif self.subagent == SubagentRole.VALIDATOR:
                if not self.command and not self.target_file:
                    errors.append(
                        f"Task '{self.task_id}' (validator) requires 'command' or 'target_file'"
                    )
            elif self.subagent in (SubagentRole.KUBECTL, SubagentRole.DOCKER, SubagentRole.GH):
                if not self.command or not self.command.strip():
                    errors.append(
                        f"Task '{self.task_id}' ({self.subagent.value}) requires a 'command' string"
                    )

        if errors:
            raise PlanValidationError("; ".join(errors), errors=errors)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TaskSpec:
        if not isinstance(data, dict):
            raise PlanValidationError(f"Task entry must be a mapping, got {type(data).__name__}")
        missing = [k for k in ("task_id", "subagent", "instruction", "on_failure") if k not in data]
        if missing:
            raise PlanValidationError(f"Task missing required fields: {missing}")

        raw_lines = data.get("target_lines")
        target_lines: tuple[int, int] | None = None
        if raw_lines is not None:
            if not isinstance(raw_lines, (list, tuple)) or len(raw_lines) != 2:
                raise PlanValidationError(
                    f"Task '{data.get('task_id')}': target_lines must be a 2-element list [start, end]"
                )
            target_lines = (int(raw_lines[0]), int(raw_lines[1]))

        expected_format_raw = data.get("expected_format")
        expected_format = ExpectedFormat(expected_format_raw) if expected_format_raw else None

        return cls(
            task_id=str(data["task_id"]),
            subagent=SubagentRole.normalize(data["subagent"]),
            instruction=str(data["instruction"]),
            on_failure=FailurePolicy(data["on_failure"]),
            command=data.get("command"),
            inputs=dict(data.get("inputs") or {}),
            target_file=data.get("target_file"),
            target_lines=target_lines,
            context_snippet=data.get("context_snippet"),
            replacement_payload=data.get("replacement_payload"),
            expected_format=expected_format,
            output_schema=data.get("output_schema"),
            expected_outcome=ExpectedOutcome.from_dict(data.get("expected_outcome")),
            depends_on=list(data.get("depends_on") or []),
            max_retries=int(data.get("max_retries", 2)),
            timeout_seconds=int(data.get("timeout_seconds", 30)),
        )

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "task_id": self.task_id,
            "subagent": self.subagent.value,
            "instruction": self.instruction,
        }
        if self.command is not None:
            out["command"] = self.command
        if self.target_file is not None:
            out["target_file"] = self.target_file
        if self.target_lines is not None:
            out["target_lines"] = [self.target_lines[0], self.target_lines[1]]
        if self.context_snippet is not None:
            out["context_snippet"] = self.context_snippet
        if self.replacement_payload is not None:
            out["replacement_payload"] = self.replacement_payload
        if self.expected_format is not None:
            out["expected_format"] = self.expected_format.value
        if self.output_schema is not None:
            out["output_schema"] = self.output_schema
        if self.inputs or self.subagent == SubagentRole.COMMAND_RUNNER:
            out["inputs"] = dict(self.inputs)
        if self.expected_outcome is not None:
            out["expected_outcome"] = self.expected_outcome.to_dict()
        if self.depends_on:
            out["depends_on"] = list(self.depends_on)
        out["on_failure"] = self.on_failure.value
        return out


@dataclass
class ExecutionPlan:
    """Top-level Planner Output Schema (Section 4)."""

    version: str
    plan_id: str
    tasks: list[TaskSpec]
    objective: str | None = None

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.version or not isinstance(self.version, str):
            errors.append("Plan 'version' must be a non-empty string")
        if not self.plan_id or not isinstance(self.plan_id, str):
            errors.append("Plan 'plan_id' must be a non-empty string")
        if not self.tasks or not isinstance(self.tasks, list):
            errors.append("Plan 'tasks' must be a non-empty list of TaskSpec items")

        seen_ids: set[str] = set()
        for task in self.tasks:
            if task.task_id in seen_ids:
                errors.append(f"Duplicate task_id '{task.task_id}' in plan '{self.plan_id}'")
            seen_ids.add(task.task_id)

        if errors:
            raise PlanValidationError("; ".join(errors), errors=errors)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExecutionPlan:
        if not isinstance(data, dict):
            raise PlanValidationError("ExecutionPlan root must be a YAML/JSON mapping")
        for req in ("version", "plan_id", "tasks"):
            if req not in data:
                raise PlanValidationError(f"ExecutionPlan missing required top-level field '{req}'")
        raw_tasks = data["tasks"]
        if not isinstance(raw_tasks, list) or not raw_tasks:
            raise PlanValidationError("ExecutionPlan 'tasks' must be a non-empty list")
        tasks = [TaskSpec.from_dict(item) for item in raw_tasks]
        return cls(
            version=str(data["version"]),
            plan_id=str(data["plan_id"]),
            tasks=tasks,
            objective=data.get("objective"),
        )

    @classmethod
    def from_yaml(cls, yaml_text: str) -> ExecutionPlan:
        parsed = load_yaml(yaml_text)
        return cls.from_dict(parsed)

    @classmethod
    def from_file(cls, path: str | Path) -> ExecutionPlan:
        file_path = Path(path)
        content = file_path.read_text(encoding="utf-8")
        if file_path.suffix.lower() == ".json":
            return cls.from_dict(json.loads(content))
        return cls.from_yaml(content)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "version": self.version,
            "plan_id": self.plan_id,
        }
        if self.objective:
            out["objective"] = self.objective
        out["tasks"] = [t.to_dict() for t in self.tasks]
        return out

    def to_yaml(self) -> str:
        return dump_yaml(self.to_dict())

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @staticmethod
    def json_schema() -> dict[str, Any]:
        """Export standard JSON Schema Draft 2020-12 for any external harness or LLM structured output."""
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "ExecutionPlan",
            "description": "Zero-Inference Micro-Task Execution Plan Schema (v1.0)",
            "type": "object",
            "required": ["version", "plan_id", "tasks"],
            "additionalProperties": False,
            "properties": {
                "version": {"type": "string", "enum": ["1.0"]},
                "plan_id": {"type": "string", "minLength": 1},
                "objective": {"type": "string"},
                "tasks": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["task_id", "subagent", "instruction", "on_failure"],
                        "properties": {
                            "task_id": {"type": "string", "minLength": 1},
                            "subagent": {
                                "type": "string",
                                "enum": [r.value for r in SubagentRole],
                            },
                            "instruction": {"type": "string", "minLength": 1},
                            "command": {"type": "string"},
                            "inputs": {"type": "object"},
                            "target_file": {"type": "string"},
                            "target_lines": {
                                "type": "array",
                                "items": {"type": "integer", "minimum": 1},
                                "minItems": 2,
                                "maxItems": 2,
                            },
                            "context_snippet": {"type": "string"},
                            "replacement_payload": {"type": "string"},
                            "expected_format": {
                                "type": "string",
                                "enum": [f.value for f in ExpectedFormat],
                            },
                            "output_schema": {"type": "object"},
                            "expected_outcome": {
                                "type": "object",
                                "properties": {
                                    "exit_code": {"type": "integer"},
                                    "stdout_contains": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "stderr_contains": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "regex_matches": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "regex_excludes": {
                                        "type": "array",
                                        "items": {"type": "string"},
                                    },
                                    "passed": {"type": "boolean"},
                                },
                            },
                            "depends_on": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                            "on_failure": {
                                "type": "string",
                                "enum": [f.value for f in FailurePolicy],
                            },
                            "max_retries": {"type": "integer", "minimum": 0, "default": 2},
                            "timeout_seconds": {"type": "integer", "minimum": 1, "default": 30},
                        },
                    },
                },
            },
        }
