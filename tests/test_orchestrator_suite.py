"""Comprehensive test suite for Micro-Task Decomposition & Subagent Orchestrator.

Compatible with both `pytest` and `python3 -m unittest discover -s tests`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from orchestrator.engine import OrchestratorEngine
from orchestrator.providers import CallableHarnessProvider, DeterministicMockProvider
from orchestrator.state import PlanStatus, TaskStatus
from planner.engine import PlannerEngine
from planner.rules import ZeroInferenceConfig, run_zero_inference_check
from planner.schema import (
    ExecutionPlan,
    FailurePolicy,
    PlanValidationError,
    SubagentRole,
    TaskSpec,
)
from subagents.base import BaseSubagent, SubagentScopeError, ToolDefinition
from subagents.command_runner import CommandExecutionResult
from validators.cli_checker import validate_cli_outcome
from validators.diff_validator import generate_unified_diff, validate_and_apply_diff
from validators.schema_validator import validate_json_schema

REPO_ROOT = Path(__file__).resolve().parent.parent


def _build_100_line_auth_service() -> str:
    """Create a realistic 100-line Python file where lines 84-92 hold the token check."""
    lines: list[str] = []
    for i in range(1, 84):
        lines.append(f"# Padding line {i}")
    # Lines 84..92 (9 lines)
    lines.extend(
        [
            "def verify_token(token, current_time):",
            "    if token is None:",
            "        raise ValueError('missing token')",
            "    if token.expires_at < current_time:",
            "        raise ExpiredTokenError()",
            "    return True",
            "# End of verify_token section line 90",
            "# Line 91",
            "# Line 92",
        ]
    )
    for i in range(93, 101):
        lines.append(f"# Trailing line {i}")
    return "\n".join(lines) + "\n"


class TestPlannerSchemaAndZeroInferenceRules(unittest.TestCase):
    def test_load_canonical_spec_yaml(self) -> None:
        planner = PlannerEngine()
        plan, report = planner.load_file(REPO_ROOT / "examples" / "auth_refactor_plan.yaml")
        self.assertEqual(plan.version, "1.0")
        self.assertEqual(plan.plan_id, "plan-2026-auth-refactor")
        self.assertEqual(len(plan.tasks), 3)
        self.assertTrue(report.passed)
        self.assertEqual(plan.tasks[1].subagent, SubagentRole.CODE_EDITOR)
        self.assertEqual(plan.tasks[1].target_lines, (84, 92))

    def test_reject_open_ended_or_multi_turn_instructions(self) -> None:
        bad_plan = ExecutionPlan.from_dict(
            {
                "version": "1.0",
                "plan_id": "bad-zero-inference",
                "tasks": [
                    {
                        "task_id": "001",
                        "subagent": "command_runner",
                        "instruction": "Figure out why auth fails as discussed earlier and if the tests fail fix it",
                        "command": "pytest -q",
                        "expected_outcome": {"exit_code": 0},
                        "on_failure": "abort_to_planner",
                    }
                ],
            }
        )
        report = run_zero_inference_check(bad_plan)
        self.assertFalse(report.passed)
        self.assertGreaterEqual(len(report.violations), 2)

    def test_reject_excessive_line_span_and_path_traversal(self) -> None:
        bad_plan = ExecutionPlan.from_dict(
            {
                "version": "1.0",
                "plan_id": "bad-slice",
                "tasks": [
                    {
                        "task_id": "001",
                        "subagent": "code_editor",
                        "instruction": "Patch target slice",
                        "target_file": "../outside_workspace.py",
                        "target_lines": [1, 500],
                        "context_snippet": "x = 1",
                        "replacement_payload": "x = 2",
                        "on_failure": "retry_with_diff_validation",
                    }
                ],
            }
        )
        report = run_zero_inference_check(
            bad_plan, ZeroInferenceConfig(max_target_line_span=150)
        )
        self.assertFalse(report.passed)
        joined = " | ".join(report.violations)
        self.assertIn("workspace-relative", joined)
        self.assertIn("context minimization bound", joined)

    def test_reject_parser_with_command_tool(self) -> None:
        with self.assertRaises(PlanValidationError):
            TaskSpec.from_dict(
                {
                    "task_id": "001",
                    "subagent": "parser",
                    "instruction": "Parse log",
                    "command": "cat app.log",
                    "output_schema": {"type": "object"},
                    "on_failure": "abort_to_planner",
                }
            )


class TestSubagentTaxonomyAndToolScoping(unittest.TestCase):
    def test_reject_generalist_subagent_with_more_than_two_tools(self) -> None:
        t1 = ToolDefinition("t1", "d1", {})
        t2 = ToolDefinition("t2", "d2", {})
        t3 = ToolDefinition("t3", "d3", {})
        with self.assertRaises(SubagentScopeError):

            class GeneralistSubagent(BaseSubagent):
                role = SubagentRole.COMMAND_RUNNER
                system_prompt = "bad"
                allowed_tools = (t1, t2, t3)


class TestDeterministicValidators(unittest.TestCase):
    def test_diff_validator_enforces_line_boundaries(self) -> None:
        content = _build_100_line_auth_service()
        # Attempt to modify line 10 when authorized slice is [84, 92]
        out_of_bounds_diff = (
            "--- a/src/auth/service.py\n"
            "+++ b/src/auth/service.py\n"
            "@@ -10,1 +10,1 @@\n"
            "-# Padding line 10\n"
            "+# Hacked line 10\n"
        )
        res = validate_and_apply_diff(
            diff_text=out_of_bounds_diff,
            target_file="src/auth/service.py",
            target_lines=(84, 92),
            full_file_content=content,
        )
        self.assertFalse(res.passed)
        self.assertIn("violate authorized target_lines boundary [84, 92]", res.summary)

    def test_schema_validator_checks_types_and_additional_properties(self) -> None:
        schema = {
            "type": "object",
            "required": ["error_type", "line"],
            "additionalProperties": False,
            "properties": {
                "error_type": {"type": "string"},
                "line": {"type": "integer", "minimum": 1},
            },
        }
        valid_res = validate_json_schema('{"error_type": "ExpiredTokenError", "line": 87}', schema)
        self.assertTrue(valid_res.passed)

        invalid_res = validate_json_schema(
            '{"error_type": "ExpiredTokenError", "line": "not-an-int", "extra": 1}',
            schema,
        )
        self.assertFalse(invalid_res.passed)
        self.assertEqual(len(invalid_res.errors), 2)

    def test_cli_validator_checks_exit_code_and_regex(self) -> None:
        plan_task = TaskSpec.from_dict(
            {
                "task_id": "001",
                "subagent": "command_runner",
                "instruction": "Run test",
                "command": "pytest",
                "expected_outcome": {
                    "exit_code": 0,
                    "stdout_contains": ["1 passed"],
                    "regex_excludes": ["FAILED", "ERROR"],
                },
                "on_failure": "abort_to_planner",
            }
        )
        res = validate_cli_outcome(
            exit_code=0,
            stdout="=== 1 passed in 0.02s ===",
            stderr="",
            expected=plan_task.expected_outcome,
        )
        self.assertTrue(res.passed)


class TestOrchestratorEndToEndLifecycle(unittest.TestCase):
    def test_execute_canonical_auth_refactor_plan(self) -> None:
        """Execute the exact 3-step plan from Section 4 of the Architecture Spec."""
        planner = PlannerEngine()
        plan, _ = planner.load_file(REPO_ROOT / "examples" / "auth_refactor_plan.yaml")

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            service_file = ws / "src" / "auth" / "service.py"
            service_file.parent.mkdir(parents=True, exist_ok=True)
            service_file.write_text(_build_100_line_auth_service(), encoding="utf-8")

            # Simulate pytest failing before patch (exit_code=1) and passing after patch (exit_code=0)
            def fake_cmd_executor(cmd: str, cwd: Path, timeout: int) -> CommandExecutionResult:
                current_code = (cwd / "src" / "auth" / "service.py").read_text(encoding="utf-8")
                if "if not token.expires_at or token.expires_at < current_time:" in current_code:
                    return CommandExecutionResult(exit_code=0, stdout="1 passed", stderr="")
                return CommandExecutionResult(exit_code=1, stdout="1 failed", stderr="")

            mock_provider = DeterministicMockProvider()
            engine = OrchestratorEngine(
                workspace_root=ws,
                inference_client=mock_provider,
                command_executor=fake_cmd_executor,
            )

            result = engine.execute_plan(plan)
            self.assertEqual(result.status, PlanStatus.COMPLETED)
            self.assertEqual(result.completed_task_ids, ["001", "002", "003"])

            # Verify that only lines 84-92 were passed to the 7B worker (Context Minimization)
            worker_calls = [c for c in mock_provider.call_history if c["role"] == "code_editor"]
            self.assertEqual(len(worker_calls), 1)
            self.assertNotIn("# Padding line 10", worker_calls[0]["user_payload"])
            self.assertIn("if token.expires_at < current_time:", worker_calls[0]["user_payload"])

            # Verify file was surgically updated on disk
            updated_text = service_file.read_text(encoding="utf-8")
            self.assertIn(
                'if not token.expires_at or token.expires_at < current_time:\n        raise ExpiredTokenError("Token missing or expired")',
                updated_text,
            )

    def test_retry_with_diff_validation_recovers_on_second_attempt(self) -> None:
        """Verify that an invalid diff on attempt 1 triggers retry_with_diff_validation."""
        planner = PlannerEngine()
        plan, _ = planner.load_file(REPO_ROOT / "examples" / "auth_refactor_plan.yaml")

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            service_file = ws / "src" / "auth" / "service.py"
            service_file.parent.mkdir(parents=True, exist_ok=True)
            service_file.write_text(_build_100_line_auth_service(), encoding="utf-8")

            # Attempt 1 returns a diff outside target_lines [84, 92]; Attempt 2 uses deterministic synthesis
            bad_diff = (
                "--- a/src/auth/service.py\n"
                "+++ b/src/auth/service.py\n"
                "@@ -5,1 +5,1 @@\n"
                "-# Padding line 5\n"
                "+# Wrong line\n"
            )
            mock_provider = DeterministicMockProvider(queued_worker_responses=[bad_diff])

            def fake_cmd_executor(cmd: str, cwd: Path, timeout: int) -> CommandExecutionResult:
                current_code = (cwd / "src" / "auth" / "service.py").read_text(encoding="utf-8")
                if "Token missing or expired" in current_code:
                    return CommandExecutionResult(exit_code=0, stdout="1 passed", stderr="")
                return CommandExecutionResult(exit_code=1, stdout="1 failed", stderr="")

            engine = OrchestratorEngine(
                workspace_root=ws,
                inference_client=mock_provider,
                command_executor=fake_cmd_executor,
            )
            result = engine.execute_plan(plan)
            self.assertTrue(result.succeeded)
            self.assertEqual(result.records["002"].attempts, 2)
            self.assertEqual(len(result.records["002"].session_ids), 2)
            # Ephemeral sessions must have distinct IDs
            self.assertNotEqual(
                result.records["002"].session_ids[0],
                result.records["002"].session_ids[1],
            )
            # Second attempt prompt must include <VALIDATION_ERROR_RETRY_FEEDBACK>
            self.assertIn(
                "<VALIDATION_ERROR_RETRY_FEEDBACK>",
                mock_provider.call_history[1]["user_payload"],
            )

    def test_full_taxonomy_pipeline_with_hydration(self) -> None:
        """Verify command_runner -> parser -> code_editor -> validator with hydration."""
        planner = PlannerEngine()
        plan, _ = planner.load_file(REPO_ROOT / "examples" / "full_taxonomy_pipeline.yaml")

        with tempfile.TemporaryDirectory() as tmpdir:
            ws = Path(tmpdir)
            service_file = ws / "src" / "auth" / "service.py"
            service_file.parent.mkdir(parents=True, exist_ok=True)
            service_file.write_text(_build_100_line_auth_service(), encoding="utf-8")

            engine = OrchestratorEngine(
                workspace_root=ws,
                inference_client=DeterministicMockProvider(),
            )
            result = engine.execute_plan(plan)
            self.assertTrue(result.succeeded)
            self.assertEqual(result.completed_task_ids, ["001", "002", "003", "004"])
            self.assertIsInstance(result.records["002"].parsed_json, dict)
            self.assertIn("error_type", result.records["002"].parsed_json)

    def test_route_to_planner_for_replan_auto_recovery(self) -> None:
        """Verify dynamic replanning when a verification task fails."""
        failing_plan = ExecutionPlan.from_dict(
            {
                "version": "1.0",
                "plan_id": "plan-initial",
                "objective": "Verify test passes",
                "tasks": [
                    {
                        "task_id": "001",
                        "subagent": "command_runner",
                        "instruction": "Run test suite",
                        "command": "pytest_initial",
                        "expected_outcome": {"exit_code": 0},
                        "on_failure": "route_to_planner_for_replan",
                    }
                ],
            }
        )
        corrective_plan_yaml = json.dumps(
            {
                "version": "1.0",
                "plan_id": "plan-replanned-recovery",
                "tasks": [
                    {
                        "task_id": "101",
                        "subagent": "command_runner",
                        "instruction": "Run corrective test command",
                        "command": "pytest_fixed",
                        "expected_outcome": {"exit_code": 0},
                        "on_failure": "abort_to_planner",
                    }
                ],
            }
        )

        mock_provider = DeterministicMockProvider(
            queued_planner_responses=[corrective_plan_yaml]
        )
        planner = PlannerEngine(provider=mock_provider)

        def fake_executor(cmd: str, cwd: Path, timeout: int) -> CommandExecutionResult:
            if cmd == "pytest_fixed":
                return CommandExecutionResult(exit_code=0, stdout="ok", stderr="")
            return CommandExecutionResult(exit_code=1, stdout="", stderr="failed")

        engine = OrchestratorEngine(
            inference_client=mock_provider,
            planner_engine=planner,
            command_executor=fake_executor,
            auto_replan=True,
        )
        result = engine.execute_plan(failing_plan)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.plan_id, "plan-replanned-recovery")
        self.assertEqual(result.replan_history, ["plan-initial"])

    def test_callable_harness_adapter(self) -> None:
        """Verify that any external harness can inject a custom callable."""
        plan = ExecutionPlan.from_dict(
            {
                "version": "1.0",
                "plan_id": "plan-custom-harness",
                "tasks": [
                    {
                        "task_id": "001",
                        "subagent": "parser",
                        "instruction": "Extract status code",
                        "inputs": {"raw": "HTTP 200 OK"},
                        "output_schema": {
                            "type": "object",
                            "required": ["code"],
                            "properties": {"code": {"type": "integer"}},
                        },
                        "on_failure": "abort_to_planner",
                    }
                ],
            }
        )
        adapter = CallableHarnessProvider(
            worker_fn=lambda sys_p, usr_p, role: '{"code": 200}'
        )
        engine = OrchestratorEngine(inference_client=adapter)
        res = engine.execute_plan(plan)
        self.assertTrue(res.succeeded)
        self.assertEqual(res.records["001"].parsed_json, {"code": 200})


    def test_devops_subagents_pipeline_execution(self) -> None:
        """Verify end-to-end execution of docker, kubectl, and gh subagents."""
        planner = PlannerEngine()
        plan, report = planner.load_file(REPO_ROOT / "examples" / "devops_pipeline.yaml")
        self.assertTrue(report.passed)
        self.assertEqual(len(plan.tasks), 3)

        # Mock responses for docker, kubectl, and gh
        def fake_devops_executor(cmd: str, cwd: Path, timeout: int) -> CommandExecutionResult:
            if "docker build" in cmd:
                return CommandExecutionResult(
                    exit_code=0,
                    stdout="Step 1/2\nStep 2/2\nSuccessfully tagged micro-app:test",
                    stderr="",
                )
            if "kubectl apply" in cmd:
                return CommandExecutionResult(
                    exit_code=0,
                    stdout=json.dumps({"kind": "Deployment", "metadata": {"name": "micro-app-deploy"}}),
                    stderr="",
                )
            if "gh release view" in cmd:
                return CommandExecutionResult(
                    exit_code=0,
                    stdout=json.dumps({"tagName": "v1.0.0", "isDraft": False}),
                    stderr="",
                )
            return CommandExecutionResult(exit_code=1, stdout="", stderr=f"Unknown command: {cmd}")

        engine = OrchestratorEngine(
            command_executor=fake_devops_executor,
            inference_client=DeterministicMockProvider(),
        )
        result = engine.execute_plan(plan)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.completed_task_ids, ["001", "002", "003"])

        # Check docker subagent record
        docker_rec = result.records["001"]
        self.assertEqual(docker_rec.subagent, SubagentRole.DOCKER)
        self.assertEqual(docker_rec.status, TaskStatus.PASSED)
        self.assertEqual(docker_rec.output.tool_calls_made, ["docker_exec"])

        # Check kubectl subagent record
        k8s_rec = result.records["002"]
        self.assertEqual(k8s_rec.subagent, SubagentRole.KUBECTL)
        self.assertEqual(k8s_rec.status, TaskStatus.PASSED)
        self.assertEqual(k8s_rec.output.tool_calls_made, ["kubectl_manifest_dry_run"])
        self.assertEqual(k8s_rec.parsed_json["kind"], "Deployment")

        # Check gh subagent record
        gh_rec = result.records["003"]
        self.assertEqual(gh_rec.subagent, SubagentRole.GH)
        self.assertEqual(gh_rec.status, TaskStatus.PASSED)
        self.assertEqual(gh_rec.output.tool_calls_made, ["gh_api_query"])
        self.assertEqual(gh_rec.parsed_json["tagName"], "v1.0.0")


if __name__ == "__main__":
    unittest.main()
