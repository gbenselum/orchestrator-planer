# Universal Agent Harness Adaptation Guide (`AGENTS.md`)

This repository is a **harness-agnostic scaffold** implementing the **Zero-Inference Micro-Task Decomposition & Subagent Orchestrator** for 7B–9B parameter models (Qwen 2.5/3.5, Gemma, Llama variants).

Any agent harness (Claude Code, Codex, Cursor, Windsurf, Cline, Aider, OpenCode, Antigravity, or custom Python/CI runners) can pick up this scaffold and adapt it to its host working environment with **zero lock-in**.

---

## 1. Repository Layout & Contracts

| Package | Responsibility | Key Entrypoints |
| :--- | :--- | :--- |
| `planner/` | Task schema, Zero-Inference decomposition linter, and Planner prompt templates | `planner/schema.py`, `planner/rules.py`, `planner/engine.py`, `planner/plan.schema.json` |
| `orchestrator/` | Decoupled state machine, bounded file-slice hydrator, and model/harness adapters | `orchestrator/engine.py`, `orchestrator/hydration.py`, `orchestrator/providers.py`, `orchestrator/cli.py` |
| `subagents/` | Ephemeral, single-turn 7B–9B worker definitions enforcing `<= 2` tools per role | `subagents/code_editor.py`, `subagents/command_runner.py`, `subagents/parser_transformer.py`, `subagents/validator_agent.py` |
| `validators/` | Deterministic verification modules (unified diff boundary checks, JSON Schema, CLI exit codes, regex filters) | `validators/diff_validator.py`, `validators/schema_validator.py`, `validators/cli_checker.py`, `validators/regex_filter.py` |
| `examples/` | Canonical YAML execution plans (`plan-2026-auth-refactor`, `plan-2026-full-taxonomy-demo`) | `examples/auth_refactor_plan.yaml`, `examples/full_taxonomy_pipeline.yaml` |

---

## 2. How Any Harness Should Adapt This Scaffold

### A. Plugging In Your Local or Remote Inference Backend
By default, `orchestrator/providers.py` provides three zero-dependency adapters:
1. **`OpenAICompatibleProvider`**: Connects to Ollama (`http://localhost:11434/v1`), vLLM (`http://localhost:8000/v1`), LM Studio (`http://localhost:1234/v1`), `llama.cpp` server, or OpenRouter using standard environment variables:
   - `MTO_API_BASE` (default: `http://localhost:11434/v1`)
   - `MTO_API_KEY` (default: `local-no-key-required`)
   - `MTO_WORKER_MODEL` (default: `qwen2.5-coder:7b`)
   - `MTO_PLANNER_MODEL` (default: falls back to `MTO_WORKER_MODEL`)
   - Supports per-role model routing via `role_models={SubagentRole.CODE_EDITOR: "qwen2.5-coder:7b", SubagentRole.PARSER: "gemma2:9b"}`.
2. **`CallableHarnessProvider`**: If your harness uses a native SDK or internal IPC bus instead of HTTP, pass a Python callback:
   ```python
   from orchestrator import CallableHarnessProvider, OrchestratorEngine

   provider = CallableHarnessProvider(
       worker_fn=lambda system_prompt, user_payload, role: my_harness_complete(system_prompt, user_payload)
   )
   engine = OrchestratorEngine(workspace_root=".", inference_client=provider)
   ```
3. **`DeterministicMockProvider`**: Offline deterministic execution for CI pipelines and dry-run verification.

### B. Plugging In Your Harness's Command Sandbox
If your harness executes shell commands inside Docker, Firecracker, Seatbelt, Bubblewrap, or a remote SSH runner, inject a custom `command_executor` into `OrchestratorEngine`:
```python
from pathlib import Path
from orchestrator import OrchestratorEngine
from subagents import CommandExecutionResult

def custom_sandbox_runner(cmd: str, cwd: Path, timeout_sec: int) -> CommandExecutionResult:
    # Route command through your harness's native sandbox tool
    exit_code, stdout, stderr = my_harness_sandbox.exec(cmd, cwd=str(cwd), timeout=timeout_sec)
    return CommandExecutionResult(exit_code=exit_code, stdout=stdout, stderr=stderr)

engine = OrchestratorEngine(workspace_root=".", command_executor=custom_sandbox_runner)
```

### C. Adapting Zero-Inference Thresholds
To tune context window slice bounds for smaller (3B/7B) or slightly larger (14B) local models, pass `ZeroInferenceConfig` to `PlannerEngine` and `OrchestratorEngine`:
```python
from planner import ZeroInferenceConfig

cfg = ZeroInferenceConfig(
    max_target_line_span=100,        # Max lines allowed in a single code_editor slice
    max_context_snippet_chars=4000,  # Max characters in context_snippet
    max_instruction_chars=500,       # Keep instructions atomic and imperative
)
```

---

## 3. Verification Commands for Agents

Run these commands to verify the environment after making any adaptations:

```bash
# 1. Validate canonical plans against Schema + Zero-Inference Linter
python3 -m orchestrator.cli validate examples/auth_refactor_plan.yaml
python3 -m orchestrator.cli validate examples/full_taxonomy_pipeline.yaml

# 2. Run the full unit and integration test suite (works with stdlib unittest or pytest)
python3 -m unittest discover -s tests -v
```
