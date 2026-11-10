"""State machine data structures for the Decoupled Orchestration Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from planner.schema import FailurePolicy, SubagentRole
from subagents.base import SubagentOutput
from validators.base import ValidationResult


class TaskStatus(str, Enum):
    """Lifecycle status of an individual atomic micro-task."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class PlanStatus(str, Enum):
    """Terminal or active status of an ExecutionPlan run."""

    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    ABORTED_TO_PLANNER = "aborted_to_planner"
    REPLAN_REQUESTED = "replan_requested"
    HALTED = "halted"


@dataclass
class TaskExecutionRecord:
    """Immutable-style record of a task's execution attempts and deterministic validation."""

    task_id: str
    subagent: SubagentRole
    status: TaskStatus = TaskStatus.PENDING
    attempts: int = 0
    session_ids: list[str] = field(default_factory=list)
    output: SubagentOutput | None = None
    validation: ValidationResult | None = None
    parsed_json: Any = None
    applied_diff: str | None = None
    failure_policy_triggered: FailurePolicy | None = None
    error_diagnostics: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "subagent": self.subagent.value,
            "status": self.status.value,
            "attempts": self.attempts,
            "session_ids": list(self.session_ids),
            "exit_code": self.output.exit_code if self.output else None,
            "validation_passed": self.validation.passed if self.validation else None,
            "validation_errors": list(self.validation.errors) if self.validation else [],
            "failure_policy_triggered": (
                self.failure_policy_triggered.value if self.failure_policy_triggered else None
            ),
            "error_diagnostics": self.error_diagnostics,
        }


@dataclass
class OrchestratorRunResult:
    """Complete execution trace and state machine outcome for an ExecutionPlan."""

    plan_id: str
    status: PlanStatus
    records: dict[str, TaskExecutionRecord] = field(default_factory=dict)
    failed_task_id: str | None = None
    replan_payload: dict[str, Any] | None = None
    replan_history: list[str] = field(default_factory=list)

    @property
    def succeeded(self) -> bool:
        return self.status == PlanStatus.COMPLETED

    @property
    def completed_task_ids(self) -> list[str]:
        return [
            tid for tid, rec in self.records.items() if rec.status == TaskStatus.PASSED
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "status": self.status.value,
            "succeeded": self.succeeded,
            "completed_task_ids": self.completed_task_ids,
            "failed_task_id": self.failed_task_id,
            "replan_payload": self.replan_payload,
            "replan_history": list(self.replan_history),
            "tasks": {tid: rec.to_dict() for tid, rec in self.records.items()},
        }
