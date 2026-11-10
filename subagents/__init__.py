"""Subagents package: lightweight system prompts and tool-scoped worker definitions."""

from subagents.base import (
    MAX_TOOLS_PER_SUBAGENT,
    BaseSubagent,
    SubagentInputPayload,
    SubagentOutput,
    SubagentScopeError,
    ToolDefinition,
    WorkerInferenceClient,
)
from subagents.code_editor import APPLY_PATCH_TOOL, CodeEditorSubagent
from subagents.command_runner import (
    RUN_COMMAND_TOOL,
    CommandExecutionResult,
    CommandExecutorFn,
    CommandRunnerSubagent,
    default_sandboxed_command_executor,
)
from subagents.docker_subagent import (
    DOCKER_EXEC_TOOL,
    DOCKER_INSPECT_TOOL,
    DockerSubagent,
)
from subagents.gh_subagent import (
    GH_API_QUERY_TOOL,
    GH_EXEC_TOOL,
    GhSubagent,
)
from subagents.kubectl_subagent import (
    KUBECTL_EXEC_TOOL,
    KUBECTL_MANIFEST_DRY_RUN_TOOL,
    KubectlSubagent,
)
from subagents.parser_transformer import ParserTransformerSubagent
from subagents.prompts import (
    CODE_EDITOR_SYSTEM_PROMPT,
    CODE_EDITOR_USER_TEMPLATE,
    COMMAND_RUNNER_SYSTEM_PROMPT,
    DOCKER_SYSTEM_PROMPT,
    GH_SYSTEM_PROMPT,
    KUBECTL_SYSTEM_PROMPT,
    PARSER_TRANSFORMER_SYSTEM_PROMPT,
    PARSER_TRANSFORMER_USER_TEMPLATE,
    VALIDATOR_SYSTEM_PROMPT,
)
from subagents.validator_agent import (
    INSPECT_FILE_READONLY_TOOL,
    RUN_READONLY_CHECK_TOOL,
    ValidatorSubagent,
)

__all__ = [
    "APPLY_PATCH_TOOL",
    "BaseSubagent",
    "CODE_EDITOR_SYSTEM_PROMPT",
    "CODE_EDITOR_USER_TEMPLATE",
    "COMMAND_RUNNER_SYSTEM_PROMPT",
    "CodeEditorSubagent",
    "CommandExecutionResult",
    "CommandExecutorFn",
    "CommandRunnerSubagent",
    "DOCKER_EXEC_TOOL",
    "DOCKER_INSPECT_TOOL",
    "DOCKER_SYSTEM_PROMPT",
    "DockerSubagent",
    "GH_API_QUERY_TOOL",
    "GH_EXEC_TOOL",
    "GH_SYSTEM_PROMPT",
    "GhSubagent",
    "INSPECT_FILE_READONLY_TOOL",
    "KUBECTL_EXEC_TOOL",
    "KUBECTL_MANIFEST_DRY_RUN_TOOL",
    "KUBECTL_SYSTEM_PROMPT",
    "KubectlSubagent",
    "MAX_TOOLS_PER_SUBAGENT",
    "PARSER_TRANSFORMER_SYSTEM_PROMPT",
    "PARSER_TRANSFORMER_USER_TEMPLATE",
    "ParserTransformerSubagent",
    "RUN_COMMAND_TOOL",
    "RUN_READONLY_CHECK_TOOL",
    "SubagentInputPayload",
    "SubagentOutput",
    "SubagentScopeError",
    "ToolDefinition",
    "VALIDATOR_SYSTEM_PROMPT",
    "ValidatorSubagent",
    "WorkerInferenceClient",
    "default_sandboxed_command_executor",
]
