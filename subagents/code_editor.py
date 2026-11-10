"""Code Editor / Patcher Subagent (`code_editor`).

Scoped to a single file-modification tool (`apply_patch`). Operates strictly on
an isolated `[start_line, end_line]` slice of `target_file`.
"""

from __future__ import annotations

from typing import Any

from planner.schema import SubagentRole, TaskSpec
from subagents.base import (
    BaseSubagent,
    SubagentOutput,
    ToolDefinition,
    WorkerInferenceClient,
)
from subagents.prompts import CODE_EDITOR_SYSTEM_PROMPT, CODE_EDITOR_USER_TEMPLATE

APPLY_PATCH_TOOL = ToolDefinition(
    name="apply_patch",
    description="Apply a validated unified diff strictly within the authorized target_lines slice.",
    parameters_schema={
        "type": "object",
        "required": ["target_file", "target_lines", "unified_diff"],
        "properties": {
            "target_file": {"type": "string"},
            "target_lines": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
            },
            "unified_diff": {"type": "string"},
        },
    },
    read_only=False,
)


class CodeEditorSubagent(BaseSubagent):
    """Single-purpose Code Editor / Patcher subagent for 7B-9B models."""

    role = SubagentRole.CODE_EDITOR
    system_prompt = CODE_EDITOR_SYSTEM_PROMPT
    allowed_tools = (APPLY_PATCH_TOOL,)

    def execute(
        self,
        task: TaskSpec,
        isolated_data: dict[str, Any],
        inference_client: WorkerInferenceClient,
        retry_feedback: str | None = None,
    ) -> SubagentOutput:
        session = self.create_ephemeral_session(task, isolated_data, retry_feedback)
        assert task.target_file is not None
        assert task.target_lines is not None

        start_line, end_line = task.target_lines
        file_slice = str(isolated_data.get("file_slice", ""))
        retry_section = (
            f"\n<VALIDATION_ERROR_RETRY_FEEDBACK>\n{retry_feedback}\n</VALIDATION_ERROR_RETRY_FEEDBACK>"
            if retry_feedback
            else ""
        )

        user_prompt = CODE_EDITOR_USER_TEMPLATE.format(
            instruction=task.instruction,
            target_file=task.target_file,
            start_line=start_line,
            end_line=end_line,
            file_slice=file_slice.rstrip("\n"),
            context_snippet=(task.context_snippet or "").rstrip("\n"),
            replacement_payload=(task.replacement_payload or "").rstrip("\n"),
            retry_section=retry_section,
        )

        raw_diff = inference_client.complete_single_turn(
            system_prompt=self.system_prompt,
            user_payload=user_prompt,
            role=self.role,
            tools=self.allowed_tools,
            response_format="unified_diff",
            temperature=0.0,
        )

        return SubagentOutput(
            session_id=session.session_id,
            task_id=task.task_id,
            role=self.role,
            raw_output=raw_diff,
            structured_output={
                "target_file": task.target_file,
                "target_lines": [start_line, end_line],
                "unified_diff": raw_diff,
            },
            tool_calls_made=["apply_patch"],
        )
