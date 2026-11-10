"""Decoupled Orchestration Engine & State Machine.

Implements Section 5 (System Execution Lifecycle) of the Architecture Spec:
1. Zero-Inference verification of incoming ExecutionPlan.
2. Ephemeral session dispatch per atomic task with isolated context slices.
3. Deterministic verification via `validators/`.
4. State transitions, retry loops, and error routing to the Planner loop.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestrator.hydration import (
    ContextHydrationError,
    hydrate_task_inputs,
    resolve_confined_path,
)
from orchestrator.providers import DeterministicMockProvider
from orchestrator.state import (
    OrchestratorRunResult,
    PlanStatus,
    TaskExecutionRecord,
    TaskStatus,
)
from planner.engine import PlannerEngine
from planner.rules import ZeroInferenceConfig, run_zero_inference_check
from planner.schema import (
    ExecutionPlan,
    FailurePolicy,
    PlanValidationError,
    SubagentRole,
    TaskSpec,
)
from subagents.base import BaseSubagent, SubagentOutput, WorkerInferenceClient
from subagents.code_editor import CodeEditorSubagent
from subagents.command_runner import CommandExecutorFn, CommandRunnerSubagent
from subagents.docker_subagent import DockerSubagent
from subagents.gh_subagent import GhSubagent
from subagents.kubectl_subagent import KubectlSubagent
from subagents.parser_transformer import ParserTransformerSubagent
from subagents.validator_agent import ValidatorSubagent
from validators.base import ValidationResult
from validators.cli_checker import validate_cli_outcome
from validators.diff_validator import validate_and_apply_diff
from validators.schema_validator import validate_json_schema


class OrchestratorEngine:
    """State machine engine managing task dispatch, context hydration, and execution graphs."""

    def __init__(
        self,
        workspace_root: str | Path = ".",
        inference_client: WorkerInferenceClient | None = None,
        planner_engine: PlannerEngine | None = None,
        command_executor: CommandExecutorFn | None = None,
        zero_inference_config: ZeroInferenceConfig | None = None,
        auto_replan: bool = False,
        max_replans: int = 2,
        dry_run_file_writes: bool = False,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.inference_client: WorkerInferenceClient = (
            inference_client or DeterministicMockProvider()
        )
        self.planner_engine = planner_engine
        self.command_executor = command_executor
        self.zero_inference_config = zero_inference_config or ZeroInferenceConfig()
        self.auto_replan = auto_replan
        self.max_replans = max_replans
        self.dry_run_file_writes = dry_run_file_writes

        self.subagents: dict[SubagentRole, BaseSubagent] = {
            SubagentRole.CODE_EDITOR: CodeEditorSubagent(),
            SubagentRole.COMMAND_RUNNER: CommandRunnerSubagent(
                workspace_root=self.workspace_root,
                command_executor=self.command_executor,
            ),
            SubagentRole.PARSER: ParserTransformerSubagent(),
            SubagentRole.TRANSFORMER: ParserTransformerSubagent(),
            SubagentRole.VALIDATOR: ValidatorSubagent(
                workspace_root=self.workspace_root,
                command_executor=self.command_executor,
            ),
            SubagentRole.KUBECTL: KubectlSubagent(
                workspace_root=self.workspace_root,
                command_executor=self.command_executor,
            ),
            SubagentRole.DOCKER: DockerSubagent(
                workspace_root=self.workspace_root,
                command_executor=self.command_executor,
            ),
            SubagentRole.GH: GhSubagent(
                workspace_root=self.workspace_root,
                command_executor=self.command_executor,
            ),
        }

    def execute_plan(self, plan: ExecutionPlan) -> OrchestratorRunResult:
        """Execute an ExecutionPlan through the deterministic state machine."""
        zi_report = run_zero_inference_check(plan, self.zero_inference_config)
        if not zi_report.passed:
            raise PlanValidationError(
                f"ExecutionPlan '{plan.plan_id}' failed Zero-Inference Test: "
                + "; ".join(zi_report.violations),
                errors=zi_report.violations,
            )

        return self._run_plan_loop(plan, replan_history=[])

    def _run_plan_loop(
        self,
        plan: ExecutionPlan,
        replan_history: list[str],
    ) -> OrchestratorRunResult:
        records: dict[str, TaskExecutionRecord] = {}
        completed_records: dict[str, TaskExecutionRecord] = {}

        for task in plan.tasks:
            record = TaskExecutionRecord(
                task_id=task.task_id,
                subagent=task.subagent,
                status=TaskStatus.RUNNING,
            )
            records[task.task_id] = record

            # Verify upstream dependencies
            missing_deps = [
                dep for dep in task.depends_on if dep not in completed_records
            ]
            if missing_deps:
                record.status = TaskStatus.FAILED
                record.error_diagnostics = (
                    f"Unmet upstream dependencies for task '{task.task_id}': {missing_deps}"
                )
                return self._handle_task_failure(
                    plan=plan,
                    task=task,
                    record=record,
                    records=records,
                    completed_records=completed_records,
                    replan_history=replan_history,
                )

            # Execute task with deterministic retry loop when configured
            task_passed = self._execute_task_with_retries(
                task=task,
                record=record,
                completed_records=completed_records,
            )

            if task_passed:
                record.status = TaskStatus.PASSED
                completed_records[task.task_id] = record
            else:
                record.status = TaskStatus.FAILED
                return self._handle_task_failure(
                    plan=plan,
                    task=task,
                    record=record,
                    records=records,
                    completed_records=completed_records,
                    replan_history=replan_history,
                )

        return OrchestratorRunResult(
            plan_id=plan.plan_id,
            status=PlanStatus.COMPLETED,
            records=records,
            replan_history=replan_history,
        )

    def _execute_task_with_retries(
        self,
        task: TaskSpec,
        record: TaskExecutionRecord,
        completed_records: dict[str, TaskExecutionRecord],
    ) -> bool:
        """Dispatch task in ephemeral sessions and validate output deterministically."""
        is_retry_policy = task.on_failure in (
            FailurePolicy.RETRY_WITH_DIFF_VALIDATION,
            FailurePolicy.RETRY_WITH_SCHEMA_VALIDATION,
        )
        max_attempts = (1 + task.max_retries) if is_retry_policy else 1
        retry_feedback: str | None = None

        subagent = self.subagents[task.subagent]

        for attempt in range(1, max_attempts + 1):
            record.attempts = attempt
            try:
                isolated_inputs = hydrate_task_inputs(
                    task=task,
                    completed_records=completed_records,
                    workspace_root=self.workspace_root,
                )
            except ContextHydrationError as exc:
                record.validation = ValidationResult(
                    passed=False,
                    validator_name="context_hydrator",
                    errors=[str(exc)],
                )
                record.error_diagnostics = str(exc)
                return False

            output = subagent.execute(
                task=task,
                isolated_data=isolated_inputs,
                inference_client=self.inference_client,
                retry_feedback=retry_feedback,
            )
            record.session_ids.append(output.session_id)
            record.output = output

            validation = self._verify_task_output(
                task=task,
                output=output,
                isolated_inputs=isolated_inputs,
                record=record,
            )
            record.validation = validation

            if validation.passed:
                record.error_diagnostics = ""
                return True

            retry_feedback = "; ".join(validation.errors)
            record.error_diagnostics = retry_feedback

        return False

    def _verify_task_output(
        self,
        task: TaskSpec,
        output: SubagentOutput,
        isolated_inputs: dict[str, Any],
        record: TaskExecutionRecord,
    ) -> ValidationResult:
        """Run the deterministic validator corresponding to the subagent's role."""
        if task.subagent in (
            SubagentRole.COMMAND_RUNNER,
            SubagentRole.VALIDATOR,
            SubagentRole.KUBECTL,
            SubagentRole.DOCKER,
            SubagentRole.GH,
        ):
            timed_out = bool(output.structured_output.get("timed_out", False))
            cli_res = validate_cli_outcome(
                exit_code=output.exit_code if output.exit_code is not None else 1,
                stdout=output.stdout,
                stderr=output.stderr,
                expected=task.expected_outcome,
                timed_out=timed_out,
            )
            # Store parsed JSON on record if output was parsed as JSON
            parsed_json = output.structured_output.get("parsed_json")
            if parsed_json is not None:
                record.parsed_json = parsed_json

            # If task also defined an output_schema, validate the parsed JSON against it
            if cli_res.passed and task.output_schema:
                schema_res = validate_json_schema(
                    output.raw_output if parsed_json is None else parsed_json,
                    task.output_schema,
                )
                if schema_res.passed and record.parsed_json is None:
                    record.parsed_json = schema_res.metadata.get("parsed_json")
                return schema_res

            return cli_res

        if task.subagent == SubagentRole.CODE_EDITOR:
            assert task.target_file is not None
            assert task.target_lines is not None
            full_content = str(isolated_inputs.get("full_file_content", ""))
            diff_result = validate_and_apply_diff(
                diff_text=output.raw_output,
                target_file=task.target_file,
                target_lines=task.target_lines,
                full_file_content=full_content,
            )
            if diff_result.passed:
                patched_content = diff_result.metadata.get("patched_content")
                record.applied_diff = output.raw_output
                if isinstance(patched_content, str) and not self.dry_run_file_writes:
                    target_path = resolve_confined_path(self.workspace_root, task.target_file)
                    target_path.write_text(patched_content, encoding="utf-8")
            return diff_result

        if task.subagent in (SubagentRole.PARSER, SubagentRole.TRANSFORMER):
            schema = task.output_schema or {"type": "object"}
            schema_result = validate_json_schema(output.raw_output, schema)
            if schema_result.passed:
                record.parsed_json = schema_result.metadata.get("parsed_json")
            return schema_result

        return ValidationResult(
            passed=False,
            validator_name="unknown_role",
            errors=[f"No deterministic validator registered for role {task.subagent}"],
        )

    def _handle_task_failure(
        self,
        plan: ExecutionPlan,
        task: TaskSpec,
        record: TaskExecutionRecord,
        records: dict[str, TaskExecutionRecord],
        completed_records: dict[str, TaskExecutionRecord],
        replan_history: list[str],
    ) -> OrchestratorRunResult:
        """Execute decoupled failure transition policy (`on_failure`)."""
        policy = task.on_failure
        record.failure_policy_triggered = policy

        replan_payload = {
            "plan_id": plan.plan_id,
            "failed_task_id": task.task_id,
            "subagent": task.subagent.value,
            "failure_policy": policy.value,
            "attempts": record.attempts,
            "completed_task_ids": list(completed_records.keys()),
            "diagnostics": record.error_diagnostics,
            "stdout": record.output.stdout if record.output else "",
            "stderr": record.output.stderr if record.output else "",
        }

        if policy == FailurePolicy.ROUTE_TO_PLANNER_FOR_REPLAN:
            if (
                self.auto_replan
                and self.planner_engine is not None
                and self.planner_engine.provider is not None
                and len(replan_history) < self.max_replans
            ):
                new_plan = self.planner_engine.replan(
                    original_plan=plan,
                    failed_task_id=task.task_id,
                    failure_policy=policy.value,
                    completed_task_ids=list(completed_records.keys()),
                    failure_diagnostics=record.error_diagnostics,
                )
                return self._run_plan_loop(
                    new_plan,
                    replan_history=[*replan_history, plan.plan_id],
                )
            return OrchestratorRunResult(
                plan_id=plan.plan_id,
                status=PlanStatus.REPLAN_REQUESTED,
                records=records,
                failed_task_id=task.task_id,
                replan_payload=replan_payload,
                replan_history=replan_history,
            )

        if policy == FailurePolicy.HALT:
            return OrchestratorRunResult(
                plan_id=plan.plan_id,
                status=PlanStatus.HALTED,
                records=records,
                failed_task_id=task.task_id,
                replan_payload=replan_payload,
                replan_history=replan_history,
            )

        # Default for ABORT_TO_PLANNER and exhausted RETRY_WITH_*_VALIDATION
        return OrchestratorRunResult(
            plan_id=plan.plan_id,
            status=PlanStatus.ABORTED_TO_PLANNER,
            records=records,
            failed_task_id=task.task_id,
            replan_payload=replan_payload,
            replan_history=replan_history,
        )
