"""Inference Providers & Universal Harness Adapters.

Provides:
1. `OpenAICompatibleProvider`: Zero-dependency HTTP client compatible with
   Ollama, vLLM, LM Studio, llama.cpp server, OpenAI, and OpenRouter.
2. `DeterministicMockProvider`: Offline deterministic inference engine for testing,
   CI validation, and dry-run execution.
3. `CallableHarnessProvider`: Adapter allowing any external agent harness to
   inject its own completion callback.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Callable

from planner.schema import SubagentRole
from subagents.base import ToolDefinition
from validators.diff_validator import generate_unified_diff


class InferenceProviderError(RuntimeError):
    """Raised when an inference backend request fails."""


class OpenAICompatibleProvider:
    """OpenAI-compatible `/v1/chat/completions` client for 7B-9B workers and planners.

    Compatible with:
    - Ollama (`http://localhost:11434/v1`, e.g., `qwen2.5-coder:7b`, `gemma2:9b`, `llama3.1:8b`)
    - vLLM (`http://localhost:8000/v1`)
    - LM Studio (`http://localhost:1234/v1`)
    - llama.cpp server (`http://localhost:8080/v1`)
    - Any OpenAI-compatible cloud or local proxy
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        default_model: str | None = None,
        planner_model: str | None = None,
        role_models: dict[SubagentRole, str] | None = None,
        timeout_seconds: int = 60,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("MTO_API_BASE") or "http://localhost:11434/v1"
        ).rstrip("/")
        self.api_key = api_key or os.environ.get("MTO_API_KEY") or "local-no-key-required"
        self.default_model = (
            default_model or os.environ.get("MTO_WORKER_MODEL") or "qwen2.5-coder:7b"
        )
        self.planner_model = (
            planner_model or os.environ.get("MTO_PLANNER_MODEL") or self.default_model
        )
        self.role_models = dict(role_models or {})
        self.timeout_seconds = timeout_seconds

    def complete_single_turn(
        self,
        system_prompt: str,
        user_payload: str,
        role: SubagentRole,
        tools: tuple[ToolDefinition, ...] = (),
        response_format: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        model = self.role_models.get(role, self.default_model)
        return self._request_chat_completion(
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_payload,
            json_mode=(response_format == "json"),
            temperature=temperature,
        )

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        return self._request_chat_completion(
            model=self.planner_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            json_mode=False,
            temperature=temperature,
        )

    def _request_chat_completion(
        self,
        model: str,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
        temperature: float = 0.0,
    ) -> str:
        url = f"{self.base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                raw_resp = resp.read().decode("utf-8")
                parsed = json.loads(raw_resp)
                return str(parsed["choices"][0]["message"]["content"])
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="replace")
            raise InferenceProviderError(
                f"HTTP {exc.code} from {url} (model={model}): {err_body}"
            ) from exc
        except (urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise InferenceProviderError(
                f"Inference request failed against {url} (model={model}): {exc}"
            ) from exc


class DeterministicMockProvider:
    """Deterministic local/dry-run provider for testing and offline verification.

    Can either replay queued responses or deterministically synthesize:
    - Unified diffs for `code_editor` tasks from `<FILE_SLICE>`, `<CONTEXT_SNIPPET>`,
      and `<REPLACEMENT_PAYLOAD>`.
    - Schema-conforming JSON objects for `parser` / `transformer` tasks.
    """

    def __init__(
        self,
        queued_worker_responses: list[str] | None = None,
        queued_planner_responses: list[str] | None = None,
    ) -> None:
        self.queued_worker_responses: list[str] = list(queued_worker_responses or [])
        self.queued_planner_responses: list[str] = list(queued_planner_responses or [])
        self.call_history: list[dict[str, Any]] = []

    def complete_single_turn(
        self,
        system_prompt: str,
        user_payload: str,
        role: SubagentRole,
        tools: tuple[ToolDefinition, ...] = (),
        response_format: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        self.call_history.append(
            {
                "type": "worker",
                "role": role.value,
                "system_prompt": system_prompt,
                "user_payload": user_payload,
                "tools": [t.name for t in tools],
                "response_format": response_format,
            }
        )
        if self.queued_worker_responses:
            return self.queued_worker_responses.pop(0)

        if role == SubagentRole.CODE_EDITOR:
            return self._synthesize_unified_diff(user_payload)
        if role in (SubagentRole.PARSER, SubagentRole.TRANSFORMER):
            return self._synthesize_schema_json(user_payload)
        return "{}"

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        self.call_history.append(
            {
                "type": "planner",
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
        )
        if self.queued_planner_responses:
            return self.queued_planner_responses.pop(0)
        raise InferenceProviderError("No queued planner response in DeterministicMockProvider")

    @staticmethod
    def _extract_tag(text: str, tag: str) -> str:
        pattern = re.compile(rf"<{tag}>\n?(.*?)\n?</{tag}>", re.DOTALL)
        match = pattern.search(text)
        return match.group(1) if match else ""

    def _synthesize_unified_diff(self, user_payload: str) -> str:
        target_file = self._extract_tag(user_payload, "TARGET_FILE").strip()
        lines_raw = self._extract_tag(user_payload, "TARGET_LINES").strip()
        start_str, _, end_str = lines_raw.partition(",")
        start_line = int(start_str) if start_str.strip().isdigit() else 1
        end_line = int(end_str) if end_str.strip().isdigit() else start_line

        file_slice = self._extract_tag(user_payload, "FILE_SLICE")
        context_snippet = self._extract_tag(user_payload, "CONTEXT_SNIPPET")
        replacement_payload = self._extract_tag(user_payload, "REPLACEMENT_PAYLOAD")

        updated_slice = _replace_snippet_preserving_indent(
            file_slice, context_snippet, replacement_payload
        )
        return generate_unified_diff(
            target_file=target_file,
            target_lines=(start_line, end_line),
            original_slice=file_slice,
            replacement_slice=updated_slice,
        )

    def _synthesize_schema_json(self, user_payload: str) -> str:
        schema_str = self._extract_tag(user_payload, "OUTPUT_SCHEMA")
        raw_input_str = self._extract_tag(user_payload, "RAW_INPUT")
        try:
            schema = json.loads(schema_str)
        except json.JSONDecodeError:
            return "{}"
        try:
            input_data = json.loads(raw_input_str)
        except json.JSONDecodeError:
            input_data = raw_input_str

        synthesized = _build_dummy_from_schema(schema, input_data)
        return json.dumps(synthesized)


class CallableHarnessProvider:
    """Adapter wrapping a custom Python callable from any external agent harness."""

    def __init__(
        self,
        worker_fn: Callable[[str, str, SubagentRole], str],
        planner_fn: Callable[[str, str], str] | None = None,
    ) -> None:
        self.worker_fn = worker_fn
        self.planner_fn = planner_fn

    def complete_single_turn(
        self,
        system_prompt: str,
        user_payload: str,
        role: SubagentRole,
        tools: tuple[ToolDefinition, ...] = (),
        response_format: str | None = None,
        temperature: float = 0.0,
    ) -> str:
        return self.worker_fn(system_prompt, user_payload, role)

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
    ) -> str:
        if self.planner_fn is None:
            raise InferenceProviderError("CallableHarnessProvider has no planner_fn configured")
        return self.planner_fn(system_prompt, user_prompt)


def _replace_snippet_preserving_indent(
    file_slice: str,
    context_snippet: str,
    replacement_payload: str,
) -> str:
    if context_snippet in file_slice:
        return file_slice.replace(context_snippet, replacement_payload, 1)

    slice_lines = file_slice.splitlines()
    ctx_lines = context_snippet.splitlines()
    rep_lines = replacement_payload.splitlines()
    n_ctx = len(ctx_lines)
    if n_ctx == 0:
        return replacement_payload

    for idx in range(len(slice_lines) - n_ctx + 1):
        window = slice_lines[idx : idx + n_ctx]
        # Check if window matches ctx_lines with a uniform leading whitespace prefix
        first_non_empty = next(
            ((w, c) for w, c in zip(window, ctx_lines) if c.strip()), None
        )
        if first_non_empty is None:
            continue
        w_line, c_line = first_non_empty
        if not w_line.endswith(c_line):
            continue
        indent = w_line[: len(w_line) - len(c_line)]
        if indent.strip() != "":
            continue
        if all(
            w == (indent + c if c.strip() else w) for w, c in zip(window, ctx_lines)
        ):
            indented_rep = [indent + r if r.strip() else "" for r in rep_lines]
            new_lines = slice_lines[:idx] + indented_rep + slice_lines[idx + n_ctx :]
            return "\n".join(new_lines) + ("\n" if file_slice.endswith("\n") else "")

    return replacement_payload


def _build_dummy_from_schema(schema: dict[str, Any], raw_input: Any) -> Any:
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    stype = schema.get("type", "object")
    if isinstance(stype, list):
        stype = stype[0]
    if stype == "object":
        props = schema.get("properties", {})
        out: dict[str, Any] = {}
        for k, prop_schema in props.items():
            if isinstance(raw_input, dict) and k in raw_input:
                out[k] = raw_input[k]
            else:
                out[k] = _build_dummy_from_schema(prop_schema, raw_input)
        return out
    if stype == "array":
        item_schema = schema.get("items", {"type": "string"})
        min_items = int(schema.get("minItems", 1))
        return [_build_dummy_from_schema(item_schema, raw_input) for _ in range(max(1, min_items))]
    if stype == "string":
        if isinstance(raw_input, str) and raw_input.strip():
            return raw_input.strip().splitlines()[0][:80]
        return "extracted_value"
    if stype == "integer":
        return int(schema.get("minimum", 0))
    if stype == "number":
        return float(schema.get("minimum", 0.0))
    if stype == "boolean":
        return True
    return None
