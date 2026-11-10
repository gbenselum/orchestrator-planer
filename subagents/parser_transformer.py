"""Parser / Transformer Subagent (`parser` / `transformer`).

Zero tools (pure generation). Transforms isolated raw text, logs, or unformatted
payloads into strict JSON conforming to `output_schema`.
"""

from __future__ import annotations

import json
from typing import Any

from planner.schema import SubagentRole, TaskSpec
from subagents.base import (
    BaseSubagent,
    SubagentOutput,
    ToolDefinition,
    WorkerInferenceClient,
)
from subagents.prompts import (
    PARSER_TRANSFORMER_SYSTEM_PROMPT,
    PARSER_TRANSFORMER_USER_TEMPLATE,
)


class ParserTransformerSubagent(BaseSubagent):
    """Zero-tool pure generation subagent for structured JSON extraction/transformation."""

    role = SubagentRole.PARSER
    system_prompt = PARSER_TRANSFORMER_SYSTEM_PROMPT
    allowed_tools: tuple[ToolDefinition, ...] = ()

    def execute(
        self,
        task: TaskSpec,
        isolated_data: dict[str, Any],
        inference_client: WorkerInferenceClient,
        retry_feedback: str | None = None,
    ) -> SubagentOutput:
        session = self.create_ephemeral_session(task, isolated_data, retry_feedback)
        schema_dict = task.output_schema or {"type": "object"}
        hydrated_inputs = isolated_data.get("inputs", task.inputs)
        if isinstance(hydrated_inputs, (dict, list)):
            raw_input_str = json.dumps(hydrated_inputs, indent=2)
        else:
            raw_input_str = str(hydrated_inputs)

        retry_section = (
            f"\n<SCHEMA_VALIDATION_ERROR_RETRY_FEEDBACK>\n{retry_feedback}\n</SCHEMA_VALIDATION_ERROR_RETRY_FEEDBACK>"
            if retry_feedback
            else ""
        )

        user_prompt = PARSER_TRANSFORMER_USER_TEMPLATE.format(
            instruction=task.instruction,
            output_schema_json=json.dumps(schema_dict, indent=2),
            raw_input=raw_input_str,
            retry_section=retry_section,
        )

        raw_json = inference_client.complete_single_turn(
            system_prompt=self.system_prompt,
            user_payload=user_prompt,
            role=task.subagent,
            tools=self.allowed_tools,
            response_format="json",
            temperature=0.0,
        )

        return SubagentOutput(
            session_id=session.session_id,
            task_id=task.task_id,
            role=task.subagent,
            raw_output=raw_json,
            structured_output={"raw_json": raw_json},
            tool_calls_made=[],
        )
