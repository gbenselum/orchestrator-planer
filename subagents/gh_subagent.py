"""GitHub CLI Operator Subagent (`gh`).

Scoped to at most two tools (`gh_exec`, `gh_api_query`).
Executes bounded GitHub operations (PRs, issues, actions, releases, API queries).
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
from subagents.prompts import GH_SYSTEM_PROMPT

GH_EXEC_TOOL = ToolDefinition(
    name="gh_exec",
    description="Execute an explicit gh command (e.g., pr create, issue list, run watch, release view).",
    parameters_schema={
        "type": "object",
        "required": ["command"],
        "properties": {
            "command": {"type": "string"},
            "repo": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 30},
        },
    },
    read_only=False,
)

GH_API_QUERY_TOOL = ToolDefinition(
    name="gh_api_query",
    description="Execute a gh api request or gh command with --json flags for structured extraction.",
    parameters_schema={
        "type": "object",
        "required": ["endpoint"],
        "properties": {
            "endpoint": {"type": "string"},
            "fields": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    },
    read_only=True,
)


class GhSubagent(BaseSubagent):
    """Scoped GitHub CLI subagent enforcing <= 2 tools."""

    role = SubagentRole.GH
    system_prompt = GH_SYSTEM_PROMPT
    allowed_tools = (GH_EXEC_TOOL, GH_API_QUERY_TOOL)

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
            raise ValueError(f"Task '{task.task_id}' (gh) has an empty command string")

        exec_result = self.command_executor(
            hydrated_command,
            self.workspace_root,
            task.timeout_seconds,
        )

        parsed_json: Any = None
        stripped_stdout = exec_result.stdout.strip()
        if "--json" in hydrated_command or "gh api" in hydrated_command or stripped_stdout.startswith(("{", "[")):
            try:
                parsed_json = json.loads(stripped_stdout)
            except json.JSONDecodeError:
                pass

        tool_used = "gh_api_query" if ("--json" in hydrated_command or "gh api" in hydrated_command) else "gh_exec"

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
