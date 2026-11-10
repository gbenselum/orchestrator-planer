"""Command-Line Interface for the Micro-Task Decomposition & Subagent Orchestrator.

Can be invoked by any agent harness, CI pipeline, or developer via:
    python3 -m orchestrator.cli validate examples/auth_refactor_plan.yaml
    python3 -m orchestrator.cli run examples/auth_refactor_plan.yaml --provider mock
    python3 -m orchestrator.cli export-schema
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from orchestrator.engine import OrchestratorEngine
from orchestrator.providers import DeterministicMockProvider, OpenAICompatibleProvider
from planner.engine import PlannerEngine
from planner.schema import ExecutionPlan, PlanValidationError
from subagents.base import WorkerInferenceClient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mto",
        description="Zero-Inference Micro-Task Decomposition & Subagent Orchestrator",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # validate
    val_parser = subparsers.add_parser(
        "validate",
        help="Validate a YAML/JSON ExecutionPlan against schema and Zero-Inference rules",
    )
    val_parser.add_argument("plan_path", help="Path to YAML or JSON plan file")
    val_parser.add_argument(
        "--json", action="store_true", help="Emit validation report as JSON"
    )

    # run
    run_parser = subparsers.add_parser(
        "run",
        help="Execute an ExecutionPlan through the decoupled orchestrator state machine",
    )
    run_parser.add_argument("plan_path", help="Path to YAML or JSON plan file")
    run_parser.add_argument(
        "--workspace",
        default=".",
        help="Workspace root directory for file slices and command execution (default: .)",
    )
    run_parser.add_argument(
        "--provider",
        choices=["mock", "openai"],
        default="mock",
        help="Inference backend: 'mock' (deterministic dry-run) or 'openai' (Ollama/vLLM/LM Studio/OpenAI)",
    )
    run_parser.add_argument(
        "--api-base",
        default=None,
        help="OpenAI-compatible base URL (default: $MTO_API_BASE or http://localhost:11434/v1)",
    )
    run_parser.add_argument(
        "--model",
        default=None,
        help="Worker model identifier (default: $MTO_WORKER_MODEL or qwen2.5-coder:7b)",
    )
    run_parser.add_argument(
        "--dry-run-writes",
        action="store_true",
        help="Validate diffs in memory without writing changes to disk",
    )
    run_parser.add_argument(
        "--json", action="store_true", help="Emit execution result trace as JSON"
    )

    # export-schema
    subparsers.add_parser(
        "export-schema",
        help="Print the JSON Schema (Draft 2020-12) for ExecutionPlan",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.subcommand == "export-schema":
        print(json.dumps(ExecutionPlan.json_schema(), indent=2))
        return 0

    if args.subcommand == "validate":
        planner = PlannerEngine()
        try:
            plan, report = planner.load_file(args.plan_path)
        except (PlanValidationError, OSError, ValueError) as exc:
            errors = getattr(exc, "errors", [str(exc)])
            if args.json:
                print(json.dumps({"valid": False, "errors": errors}, indent=2))
            else:
                print(f"[FAIL] Plan validation failed for '{args.plan_path}':", file=sys.stderr)
                for err in errors:
                    print(f"  - {err}", file=sys.stderr)
            return 1

        if args.json:
            print(
                json.dumps(
                    {
                        "valid": True,
                        "plan_id": plan.plan_id,
                        "version": plan.version,
                        "task_count": len(plan.tasks),
                        "zero_inference_passed": report.passed,
                    },
                    indent=2,
                )
            )
        else:
            print(
                f"[PASS] Plan '{plan.plan_id}' (v{plan.version}) passed schema & "
                f"Zero-Inference checks ({len(plan.tasks)} atomic tasks)."
            )
        return 0

    if args.subcommand == "run":
        planner = PlannerEngine()
        try:
            plan, _ = planner.load_file(args.plan_path)
        except (PlanValidationError, OSError, ValueError) as exc:
            print(f"[ERROR] Invalid plan: {exc}", file=sys.stderr)
            return 1

        client: WorkerInferenceClient
        if args.provider == "openai":
            client = OpenAICompatibleProvider(
                base_url=args.api_base,
                default_model=args.model,
            )
        else:
            client = DeterministicMockProvider()

        engine = OrchestratorEngine(
            workspace_root=Path(args.workspace),
            inference_client=client,
            planner_engine=planner,
            dry_run_file_writes=args.dry_run_writes,
        )
        result = engine.execute_plan(plan)

        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print(f"Plan ID : {result.plan_id}")
            print(f"Status  : {result.status.value.upper()}")
            for tid, rec in result.records.items():
                print(
                    f"  - Task {tid} [{rec.subagent.value}]: {rec.status.value.upper()} "
                    f"(attempts={rec.attempts})"
                )
                if rec.error_diagnostics:
                    print(f"      diagnostics: {rec.error_diagnostics}")
        return 0 if result.succeeded else 2

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
