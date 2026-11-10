"""Base contracts for ephemeral, tool-scoped 7B-9B worker subagents.

Enforces Section 2 (Context Minimization, Hermetic Contracts, Tool Scoping via
Subagents) and Section 3 (Subagent Taxonomy) of the Architecture Spec.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from planner.schema import SubagentRole, TaskSpec

MAX_TOOLS_PER_SUBAGENT = 2


class SubagentScopeError(ValueError):
    """Raised when a subagent configuration violates tool scoping or isolation constraints."""


@dataclass(frozen=True)
class ToolDefinition:
    """Explicit tool declaration scoped to a subagent."""

    name: str
    description: str
    parameters_schema: dict[str, Any]
    read_only: bool = False


@dataclass
class SubagentInputPayload:
    """Strictly bounded, ephemeral input payload hydrated for a single task."""

    session_id: str
    task_id: str
    role: SubagentRole
    instruction: str
    isolated_data: dict[str, Any] = field(default_factory=dict)
    retry_feedback: str | None = None


@dataclass
class SubagentOutput:
    """Structured output returned by an ephemeral subagent execution."""

    session_id: str
    task_id: str
    role: SubagentRole
    raw_output: str
    structured_output: dict[str, Any] = field(default_factory=dict)
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    tool_calls_made: list[str] = field(default_factory=list)


class WorkerInferenceClient(Protocol):
    """Protocol for 7B-9B model inference (OpenAI-compatible HTTP, local runner, or mock)."""

    def complete_single_turn(
        self,
        system_prompt: str,
        user_payload: str,
        role: SubagentRole,
        tools: tuple[ToolDefinition, ...] = (),
        response_format: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        ...


class BaseSubagent:
    """Base class for all specialized subagents enforcing <= 2 tools and stateless execution."""

    role: SubagentRole
    system_prompt: str
    allowed_tools: tuple[ToolDefinition, ...] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        tools = getattr(cls, "allowed_tools", ())
        if len(tools) > MAX_TOOLS_PER_SUBAGENT:
            raise SubagentScopeError(
                f"Subagent '{cls.__name__}' defines {len(tools)} tools; "
                f"Architecture Spec permits at most {MAX_TOOLS_PER_SUBAGENT} tools per subagent."
            )

    def create_ephemeral_session(
        self,
        task: TaskSpec,
        isolated_data: dict[str, Any],
        retry_feedback: str | None = None,
    ) -> SubagentInputPayload:
        """Create a fresh, zero-history session payload for a single atomic task."""
        return SubagentInputPayload(
            session_id=f"ephem-{task.task_id}-{uuid.uuid4().hex[:8]}",
            task_id=task.task_id,
            role=self.role,
            instruction=task.instruction,
            isolated_data=dict(isolated_data),
            retry_feedback=retry_feedback,
        )

    def execute(
        self,
        task: TaskSpec,
        isolated_data: dict[str, Any],
        inference_client: WorkerInferenceClient,
        retry_feedback: str | None = None,
    ) -> SubagentOutput:
        """Execute the atomic task inside an ephemeral session."""
        raise NotImplementedError
