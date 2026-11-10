"""Validator Subagent (`validator`).

Scoped to read-only check tools (`run_readonly_check`, `inspect_file_readonly`).
Executes deterministic verification commands (pytest, ruff, cargo check) and
produces a boolean status + structured failure log.
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
from subagents.command_runner import CommandExecutorFn, default_sandboxed_command_executor
from subagents.prompts import VALIDATOR_SYSTEM_PROMPT

RUN_READONLY_CHECK_TOOL = ToolDefinition(
    name="run_readonly_check",
    description="Execute a read-only verification command (e.g., pytest, ruff, cargo check).",
    parameters_schema={
        "type": "object",
        "required": ["command"],
        "properties": {
            "command": {"type": "string"},
        },
    },
    read_only=True,
)

INSPECT_FILE_READONLY_TOOL = ToolDefinition(
    name="inspect_file_readonly",
    description="Read-only inspection of a file slice for syntax or pattern verification.",
    parameters_schema={
        "type": "object",
        "required": ["target_file"],
        "properties": {
            "target_file": {"type": "string"},
        },
    },
    read_only=True,
)


class ValidatorSubagent(BaseSubagent):
    """Read-only Validator subagent producing boolean status and structured failure logs."""

    role = SubagentRole.VALIDATOR
    system_prompt = VALIDATOR_SYSTEM_PROMPT
    allowed_tools = (RUN_READONLY_CHECK_TOOL, INSPECT_FILE_READONLY_TOOL)

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

        if hydrated_command:
            exec_res = self.command_executor(
                hydrated_command,
                self.workspace_root,
                task.timeout_seconds,
            )
            expected_exit = (
                task.expected_outcome.exit_code
                if (task.expected_outcome and task.expected_outcome.exit_code is not None)
                else 0
            )
            passed = (exec_res.exit_code == expected_exit) and not exec_res.timed_out
            failure_log = "" if passed else f"{exec_res.stdout}\n{exec_res.stderr}".strip()
            report = {
                "passed": passed,
                "exit_code": exec_res.exit_code,
                "command": hydrated_command,
                "failure_log": failure_log,
            }
            return SubagentOutput(
                session_id=session.session_id,
                task_id=task.task_id,
                role=self.role,
                raw_output=json.dumps(report),
                structured_output=report,
                exit_code=exec_res.exit_code,
                stdout=exec_res.stdout,
                stderr=exec_res.stderr,
                tool_calls_made=["run_readonly_check"],
            )

        # File inspection fallback
        file_slice = str(isolated_data.get("file_slice", ""))
        passed = bool(file_slice)
        report = {
            "passed": passed,
            "exit_code": 0 if passed else 1,
            "target_file": task.target_file,
            "failure_log": "" if passed else f"Target file '{task.target_file}' slice was empty or missing",
        }
        return SubagentOutput(
            session_id=session.session_id,
            task_id=task.task_id,
            role=self.role,
            raw_output=json.dumps(report),
            structured_output=report,
            exit_code=0 if passed else 1,
            stdout=file_slice,
            stderr="",
            tool_calls_made=["inspect_file_readonly"],
        )
