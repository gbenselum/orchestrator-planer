"""Docker Container Engine Operator Subagent (`docker`).

Scoped to at most two container tools (`docker_exec`, `docker_inspect`).
Executes bounded docker builds, container runs, compose tasks, and image inspections.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from planner.schema import SubagentRole, TaskSpec
from subagents.base import (
    BaseSubagent,
    SubagentOutput,
    ToolDefinition,
    WorkerInferenceClient,
)
from subagents.command_runner import (
    CommandExecutorFn,
    default_sandboxed_command_executor,
)
from subagents.prompts import DOCKER_SYSTEM_PROMPT

DOCKER_EXEC_TOOL = ToolDefinition(
    name="docker_exec",
    description="Execute an explicit docker or docker compose command (e.g., build, run, compose up, ps).",
    parameters_schema={
        "type": "object",
        "required": ["command"],
        "properties": {
            "command": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 60},
        },
    },
    read_only=False,
)

DOCKER_INSPECT_TOOL = ToolDefinition(
    name="docker_inspect",
    description="Inspect a container, image, or network returning deterministic JSON metadata.",
    parameters_schema={
        "type": "object",
        "required": ["target"],
        "properties": {
            "target": {"type": "string"},
            "format": {"type": "string"},
        },
    },
    read_only=True,
)


class DockerSubagent(BaseSubagent):
    """Scoped Docker container engine subagent enforcing <= 2 tools."""

    role = SubagentRole.DOCKER
    system_prompt = DOCKER_SYSTEM_PROMPT
    allowed_tools = (DOCKER_EXEC_TOOL, DOCKER_INSPECT_TOOL)

    def __init__(
        self,
        workspace_root: str | Path = ".",
        command_executor: CommandExecutorFn | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.command_executor = command_executor or default_sandboxed_command_executor

    def execute(
        self,
        task: TaskSpec,
        isolated_data: dict[str, Any],
        inference_client: WorkerInferenceClient,
        retry_feedback: str | None = None,
    ) -> SubagentOutput:
        session = self.create_ephemeral_session(task, isolated_data, retry_feedback)
        hydrated_command = str(isolated_data.get("command") or task.command or "")
        if not hydrated_command.strip():
            raise ValueError(f"Task '{task.task_id}' (docker) has an empty command string")

        exec_result = self.command_executor(
            hydrated_command,
            self.workspace_root,
            task.timeout_seconds,
        )

        parsed_json: Any = None
        stripped_stdout = exec_result.stdout.strip()
        if "inspect" in hydrated_command or "--format '{{json" in hydrated_command or stripped_stdout.startswith(("{", "[")):
            try:
                parsed_json = json.loads(stripped_stdout)
            except json.JSONDecodeError:
                pass

        tool_used = "docker_inspect" if "docker inspect" in hydrated_command else "docker_exec"

        return SubagentOutput(
            session_id=session.session_id,
            task_id=task.task_id,
            role=self.role,
            raw_output=exec_result.stdout,
            structured_output={
                "command": hydrated_command,
                "exit_code": exec_result.exit_code,
                "stdout": exec_result.stdout,
                "stderr": exec_result.stderr,
                "timed_out": exec_result.timed_out,
                "parsed_json": parsed_json,
            },
            exit_code=exec_result.exit_code,
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
            tool_calls_made=[tool_used],
        )
