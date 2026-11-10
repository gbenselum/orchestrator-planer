"""Kubernetes Cluster & Manifest Operator Subagent (`kubectl`).

Scoped to at most two Kubernetes tools (`kubectl_exec`, `kubectl_manifest_dry_run`).
Executes bounded cluster commands and manifest dry-run assertions without conversational overhead.
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
from subagents.prompts import KUBECTL_SYSTEM_PROMPT

KUBECTL_EXEC_TOOL = ToolDefinition(
    name="kubectl_exec",
    description="Execute an explicit kubectl CLI command (e.g., get, apply, rollout, describe).",
    parameters_schema={
        "type": "object",
        "required": ["command"],
        "properties": {
            "command": {"type": "string"},
            "namespace": {"type": "string"},
            "context": {"type": "string"},
            "timeout_seconds": {"type": "integer", "default": 30},
        },
    },
    read_only=False,
)

KUBECTL_MANIFEST_DRY_RUN_TOOL = ToolDefinition(
    name="kubectl_manifest_dry_run",
    description="Validate Kubernetes manifest syntax and server schema via client/server dry-run.",
    parameters_schema={
        "type": "object",
        "required": ["manifest_path"],
        "properties": {
            "manifest_path": {"type": "string"},
            "dry_run_type": {
                "type": "string",
                "enum": ["client", "server"],
                "default": "client",
            },
        },
    },
    read_only=True,
)


class KubectlSubagent(BaseSubagent):
    """Scoped Kubernetes subagent enforcing <= 2 tools."""

    role = SubagentRole.KUBECTL
    system_prompt = KUBECTL_SYSTEM_PROMPT
    allowed_tools = (KUBECTL_EXEC_TOOL, KUBECTL_MANIFEST_DRY_RUN_TOOL)

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
            raise ValueError(f"Task '{task.task_id}' (kubectl) has an empty command string")

        exec_result = self.command_executor(
            hydrated_command,
            self.workspace_root,
            task.timeout_seconds,
        )

        # Attempt JSON decoding if `-o json` was requested or output is a JSON payload
        parsed_json: Any = None
        if "-o json" in hydrated_command or "-o=json" in hydrated_command or exec_result.stdout.strip().startswith(("{", "[")):
            try:
                parsed_json = json.loads(exec_result.stdout.strip())
            except json.JSONDecodeError:
                pass

        tool_used = "kubectl_manifest_dry_run" if "--dry-run" in hydrated_command else "kubectl_exec"

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
