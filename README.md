# Micro-Task Decomposition & Subagent Orchestrator

A portable, harness-agnostic **"Plan & Execute" scaffold** that decomposes complex software and operational objectives into atomic micro-tasks executable by lightweight local or open-weights models (**7B–9B parameter class**, such as Qwen 2.5/3.5, Gemma 2/3, or Llama 3.x).

## Core Design Principles

1. **Zero-Inference Execution**: Worker models never assume context, retain multi-turn conversation state, or navigate conditional branching logic.
2. **Context Minimization**: Workers receive strictly bounded, ephemeral context slices (e.g., `target_lines: [84, 92]` of a single file) rather than full files or repository trees.
3. **Hermetic Contracts**: Every task acts as a pure function with deterministic inputs, explicit constraints, and rigidly validated outputs (unified diffs, JSON schemas, or CLI exit codes).
4. **Tool Scoping via Subagents**: Generalist multi-tool workers are prohibited (`MAX_TOOLS_PER_SUBAGENT = 2`). Each task maps to a single-purpose subagent role.
5. **Deterministic Verification**: No LLM self-critique. Task outputs are verified deterministically via `validators/` (line-bounded unified diff checks, JSON Schema validators, regex matchers, and CLI return codes).
6. **Decoupled Orchestration**: State transitions, retry loops (`retry_with_diff_validation`, `retry_with_schema_validation`), and error escalations (`abort_to_planner`, `route_to_planner_for_replan`) live exclusively in the `orchestrator/` state machine.

---

## Subagent Taxonomy

| Role (`subagent`) | Toolset Scope | Input Payload | Deterministic Validator |
| :--- | :--- | :--- | :--- |
| `code_editor` | `apply_patch` (1 tool) | `target_file`, `target_lines: [start, end]`, isolated `file_slice`, `context_snippet`, `replacement_payload` | `validators.diff_validator` (verifies hunk syntax, file match, and strict `[start, end]` line bounds) |
| `command_runner` | `run_command` (1 tool) | Explicit CLI `command` string | `validators.cli_checker` (verifies `exit_code`, `stdout_contains`, `stderr_contains`, regexes) |
| `docker` | `docker_exec`, `docker_inspect` (2 tools) | Bounded container/compose command | `validators.cli_checker` + JSON parser |
| `kubectl` | `kubectl_exec`, `kubectl_manifest_dry_run` (2 tools) | Bounded kubectl command or manifest check | `validators.cli_checker` + JSON schema check |
| `gh` | `gh_exec`, `gh_api_query` (2 tools) | Bounded GitHub CLI operation | `validators.cli_checker` + JSON schema check |
| `parser` / `transformer` | Zero tools (`0` tools) | Isolated `inputs` (raw text, logs, unformatted strings) | `validators.schema_validator` (verifies strict JSON Schema compliance) |
| `validator` | `run_readonly_check`, `inspect_file_readonly` (2 read-only tools) | Read-only check command (`pytest`, `ruff`, `cargo check`) | `validators.cli_checker` (emits boolean pass status + structured failure log) |

> See **[future.md](file:///Users/gabriel/Projects/orchestrator-planer/future.md)** for the complete roadmap of 18+ upcoming DevOps subagents mapped to roadmap.sh (Terraform, Helm, ArgoCD, Ansible, AWS, Vault, Trivy, etc.).

---

## Repository Structure

```text
.
├── AGENTS.md                        # Harness adaptation guide (Codex, Claude Code, Cursor, Aider, etc.)
├── pyproject.toml                   # PEP 621 package metadata (works with uv/pip or bare Python 3.11+ stdlib)
├── planner/
│   ├── schema.py                    # ExecutionPlan, TaskSpec, SubagentRole, FailurePolicy models
│   ├── plan.schema.json             # Exported JSON Schema (Draft 2020-12)
│   ├── rules.py                     # Zero-Inference Test linter & context bound verifier
│   ├── prompts.py                   # System prompts for initial decomposition & error-driven replanning
│   ├── engine.py                    # PlannerEngine (decomposition, validation, replanning)
│   └── compat.py                    # PyYAML/Pydantic v2 integration with zero-dependency stdlib fallback
├── orchestrator/
│   ├── state.py                     # TaskStatus, PlanStatus, TaskExecutionRecord, OrchestratorRunResult
│   ├── hydration.py                 # Confined file-slice extractor & {{tasks.<id>.<field>}} hydrator
│   ├── providers.py                 # OpenAICompatibleProvider (Ollama/vLLM/LM Studio), Mock, & Callable adapters
│   ├── engine.py                    # Decoupled state machine & retry/replan loop
│   └── cli.py                       # CLI entrypoint (`python3 -m orchestrator.cli`)
├── subagents/
│   ├── base.py                      # BaseSubagent enforcing <= 2 tools and ephemeral session IDs
│   ├── prompts.py                   # Token-minimal system prompt templates for 7B-9B workers
│   ├── code_editor.py               # CodeEditorSubagent
│   ├── command_runner.py            # CommandRunnerSubagent
│   ├── parser_transformer.py        # ParserTransformerSubagent (0 tools)
│   └── validator_agent.py           # ValidatorSubagent (read-only)
├── validators/
│   ├── diff_validator.py            # Unified diff parser, line-bound verifier, & surgical patch applicator
│   ├── schema_validator.py          # Deterministic JSON Schema validator
│   ├── cli_checker.py               # Exit code, stdout/stderr substring, and timeout checker
│   └── regex_filter.py              # Regex inclusion/exclusion filters & code-fence stripper
├── examples/
│   ├── auth_refactor_plan.yaml      # Canonical Section 4 spec plan
│   └── full_taxonomy_pipeline.yaml  # End-to-end 4-subagent pipeline with output hydration
└── tests/
    └── test_orchestrator_suite.py   # Comprehensive unit & integration test suite
```

---

## Quick Start

> **Zero-Dependency Portability**: This scaffold runs immediately on any Python 3.11+ interpreter using the standard library alone, and automatically leverages `pydantic`, `pyyaml`, and `pytest` when installed.

### 1. Validate a Plan (Schema + Zero-Inference Test)
```bash
python3 -m orchestrator.cli validate examples/auth_refactor_plan.yaml
python3 -m orchestrator.cli validate examples/full_taxonomy_pipeline.yaml --json
```

### 2. Run With Local 7B–9B Models (Ollama / vLLM / LM Studio / llama.cpp)
```bash
export MTO_API_BASE="http://localhost:11434/v1"
export MTO_WORKER_MODEL="qwen2.5-coder:7b"

python3 -m orchestrator.cli run examples/auth_refactor_plan.yaml \
  --provider openai \
  --workspace /path/to/target/repo
```

### 3. Export the JSON Schema for External Harnesses
```bash
python3 -m orchestrator.cli export-schema
```

### 4. Run the Test Suite
```bash
python3 -m unittest discover -s tests -v
```
