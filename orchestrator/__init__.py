"""Orchestrator package: state machine engine, context hydration, and provider adapters."""

from orchestrator.engine import OrchestratorEngine
from orchestrator.hydration import (
    ContextHydrationError,
    extract_file_slice,
    hydrate_task_inputs,
    hydrate_template_string,
    resolve_confined_path,
)
from orchestrator.providers import (
    CallableHarnessProvider,
    DeterministicMockProvider,
    InferenceProviderError,
    OpenAICompatibleProvider,
)
from orchestrator.state import (
    OrchestratorRunResult,
    PlanStatus,
    TaskExecutionRecord,
    TaskStatus,
)

__all__ = [
    "CallableHarnessProvider",
    "ContextHydrationError",
    "DeterministicMockProvider",
    "InferenceProviderError",
    "OpenAICompatibleProvider",
    "OrchestratorEngine",
    "OrchestratorRunResult",
    "PlanStatus",
    "TaskExecutionRecord",
    "TaskStatus",
    "extract_file_slice",
    "hydrate_task_inputs",
    "hydrate_template_string",
    "resolve_confined_path",
]
