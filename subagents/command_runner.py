"""Command Runner Subagent (`command_runner`).

Scoped to a single sandboxed shell execution tool (`run_command`). Executes
explicit CLI command strings without conversational overhead.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from planner.schema import SubagentRole, TaskSpec
from subagents.base import (
    BaseSubagent,
    SubagentOutput,
    ToolDefinition,
    WorkerInferenceClient,
)
from subagents.prompts import COMMAND_RUNNER_SYSTEM_PROMPT

RUN_COMMAND_TOOL = ToolDefinition(
    name="run_command",
    description="Execute an explicit CLI command string inside the workspace sandbox.",
    parameters_schema={
        "type": "object",
        "required": ["command"],
        "properties": {
            "command": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 30},
        },
    },
    read_only=False,
)


@dataclass
class CommandExecutionResult:
    """Raw result from sandboxed command execution."""

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


CommandExecutorFn = Callable[[str, Path, int], CommandExecutionResult]


def default_sandboxed_command_executor(
    command: str,
    workspace_root: Path,
    timeout_seconds: int = 30,
) -> CommandExecutionResult:
    """Execute a command string inside `workspace_root` with timeout enforcement."""
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return CommandExecutionResult(
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
        )
    except subprocess.TimeoutExpired as exc:
        return CommandExecutionResult(
            exit_code=124,
            stdout=exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or ""),
            stderr=exc.stderr.decode("utf-8", errors="replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "Command timed out"),
            timed_out=True,
        )


class CommandRunnerSubagent(BaseSubagent):
    """Single-purpose Command Runner subagent."""

    role = SubagentRole.COMMAND_RUNNER
    system_prompt = COMMAND_RUNNER_SYSTEM_PROMPT
    allowed_tools = (RUN_COMMAND_TOOL,)

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
            raise ValueError(f"Task '{task.task_id}' has an empty command string")

        exec_result = self.command_executor(
            hydrated_command,
            self.workspace_root,
            task.timeout_seconds,
        )

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
            },
            exit_code=exec_result.exit_code,
            stdout=exec_result.stdout,
            stderr=exec_result.stderr,
            tool_calls_made=["run_command"],
        )
