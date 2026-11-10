"""Planner Engine for task decomposition, Zero-Inference linting, and replanning."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from planner.prompts import (
    PLANNER_DECOMPOSITION_USER_TEMPLATE,
    PLANNER_REPLAN_USER_TEMPLATE,
    PLANNER_SYSTEM_PROMPT,
)
from planner.rules import ZeroInferenceConfig, ZeroInferenceReport, run_zero_inference_check
from planner.schema import ExecutionPlan, PlanValidationError

CODE_FENCE_RE = re.compile(r"^```(?:yaml|yml|json)?\s*\n(.*?)\n```\s*$", re.DOTALL)


class PlannerInferenceProvider(Protocol):
    """Protocol for any LLM backend or harness adapter used by the Planner."""

    def generate(self, system_prompt: str, user_prompt: str, temperature: float = 0.0) -> str:
        ...


def strip_markdown_fences(raw_text: str) -> str:
    """Strip surrounding markdown code fences from raw LLM output if present."""
    stripped = raw_text.strip()
    match = CODE_FENCE_RE.match(stripped)
    if match:
        return match.group(1).strip()
    return stripped


class PlannerEngine:
    """Decomposes high-level objectives into validated Zero-Inference ExecutionPlans."""

    def __init__(
        self,
        provider: PlannerInferenceProvider | None = None,
        zero_inference_config: ZeroInferenceConfig | None = None,
    ) -> None:
        self.provider = provider
        self.zero_inference_config = zero_inference_config or ZeroInferenceConfig()

    def parse_and_validate(self, raw_plan_text: str) -> tuple[ExecutionPlan, ZeroInferenceReport]:
        """Parse YAML/JSON plan text and run both schema and Zero-Inference checks."""
        cleaned = strip_markdown_fences(raw_plan_text)
        plan = ExecutionPlan.from_yaml(cleaned)
        report = run_zero_inference_check(plan, self.zero_inference_config)
        if not report.passed:
            raise PlanValidationError(
                f"Plan '{plan.plan_id}' failed Zero-Inference Test: "
                + "; ".join(report.violations),
                errors=report.violations,
            )
        return plan, report

    def load_file(self, path: str | Path) -> tuple[ExecutionPlan, ZeroInferenceReport]:
        """Load and validate an ExecutionPlan from a YAML or JSON file."""
        content = Path(path).read_text(encoding="utf-8")
        return self.parse_and_validate(content)

    def decompose(self, objective: str, workspace_context: str = "") -> ExecutionPlan:
        """Decompose a high-level user objective into a validated ExecutionPlan."""
        if self.provider is None:
            raise RuntimeError(
                "PlannerEngine requires an inference provider to decompose dynamic objectives"
            )
        user_prompt = PLANNER_DECOMPOSITION_USER_TEMPLATE.format(
            objective=objective.strip(),
            workspace_context=workspace_context.strip() or "(empty context)",
        )
        raw_output = self.provider.generate(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
        )
        plan, _ = self.parse_and_validate(raw_output)
        return plan

    def replan(
        self,
        original_plan: ExecutionPlan,
        failed_task_id: str,
        failure_policy: str,
        completed_task_ids: list[str],
        failure_diagnostics: str,
    ) -> ExecutionPlan:
        """Generate a corrective ExecutionPlan when deterministic verification fails."""
        if self.provider is None:
            raise RuntimeError(
                "PlannerEngine requires an inference provider to execute dynamic replanning"
            )
        user_prompt = PLANNER_REPLAN_USER_TEMPLATE.format(
            plan_id=original_plan.plan_id,
            objective=original_plan.objective or "(unspecified objective)",
            failed_task_id=failed_task_id,
            failure_policy=failure_policy,
            completed_task_ids=completed_task_ids,
            failure_diagnostics=failure_diagnostics,
        )
        raw_output = self.provider.generate(
            system_prompt=PLANNER_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            temperature=0.0,
        )
        plan, _ = self.parse_and_validate(raw_output)
        return plan
