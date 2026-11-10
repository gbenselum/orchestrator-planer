"""Compatibility layer for multi-environment execution.

Uses PyYAML and Pydantic v2 when installed in the host environment, while
providing deterministic pure-stdlib fallbacks so any agent harness or container
can execute the scaffold immediately with zero external dependencies.
"""

from __future__ import annotations

import json
import re
from typing import Any

try:
    import yaml as _pyyaml  # type: ignore[import-untyped]

    HAS_PYYAML = True
except ImportError:
    _pyyaml = None
    HAS_PYYAML = False

try:
    import pydantic as _pydantic  # type: ignore[import-not-found]

    HAS_PYDANTIC = True
except ImportError:
    _pydantic = None
    HAS_PYDANTIC = False


def load_yaml(text: str) -> Any:
    """Parse YAML or JSON text into Python data structures."""
    stripped = text.strip()
    if not stripped:
        return {}
    if HAS_PYYAML and _pyyaml is not None:
        return _pyyaml.safe_load(text)
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(stripped)
    return _stdlib_parse_yaml(text)


def dump_yaml(data: Any) -> str:
    """Serialize Python data structures into clean YAML."""
    if HAS_PYYAML and _pyyaml is not None:
        return _pyyaml.safe_dump(data, sort_keys=False, default_flow_style=False)
    return _stdlib_dump_yaml(data, indent=0)


# ---------------------------------------------------------------------------
# Pure-Python YAML subset parser & emitter (for bare stdlib environments)
# Supports: mappings, sequences, block scalars (| and >), inline JSON arrays
# and objects, numbers, booleans, quoted strings, and comments.
# ---------------------------------------------------------------------------


def _parse_scalar(val: str) -> Any:
    val = val.strip()
    if not val:
        return None
    if val in ("{}", "[]") or val.startswith("{") or val.startswith("["):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            if val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                if not inner:
                    return []
                return [_parse_scalar(part) for part in inner.split(",")]
    if (val.startswith('"') and val.endswith('"')) or (
        val.startswith("'") and val.endswith("'")
    ):
        if val.startswith('"'):
            try:
                return json.loads(val)
            except json.JSONDecodeError:
                return val[1:-1]
        return val[1:-1]
    lower = val.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    if lower in ("null", "none", "~"):
        return None
    if re.fullmatch(r"-?\d+", val):
        return int(val)
    if re.fullmatch(r"-?\d+\.\d+", val):
        return float(val)
    return val


def _strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for idx, ch in enumerate(line):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            if idx == 0 or line[idx - 1].isspace():
                return line[:idx].rstrip()
    return line.rstrip()


def _stdlib_parse_yaml(text: str) -> Any:
    raw_lines = text.splitlines()
    idx = 0
    n = len(raw_lines)

    def _next_meaningful(pos: int) -> int:
        while pos < n:
            cleaned = _strip_comment(raw_lines[pos])
            if cleaned.strip():
                return pos
            pos += 1
        return pos

    def _indent_of(line: str) -> int:
        return len(line) - len(line.lstrip(" "))

    def _parse_block_scalar(start_idx: int, parent_indent: int, folded: bool) -> tuple[str, int]:
        block_lines: list[str] = []
        block_indent: int | None = None
        cur = start_idx
        while cur < n:
            raw = raw_lines[cur]
            if not raw.strip():
                block_lines.append("")
                cur += 1
                continue
            ind = _indent_of(raw)
            if block_indent is None:
                if ind <= parent_indent:
                    break
                block_indent = ind
            if ind < block_indent:
                break
            block_lines.append(raw[block_indent:])
            cur += 1
        while block_lines and block_lines[-1] == "":
            block_lines.pop()
        joiner = " " if folded else "\n"
        result = joiner.join(block_lines) + ("\n" if block_lines else "")
        return result, cur

    def _parse_node(start_idx: int, min_indent: int) -> tuple[Any, int]:
        pos = _next_meaningful(start_idx)
        if pos >= n:
            return {}, pos
        first_line = _strip_comment(raw_lines[pos])
        base_indent = _indent_of(first_line)
        if base_indent < min_indent:
            return {}, pos

        if first_line.lstrip(" ").startswith("- ") or first_line.lstrip(" ") == "-":
            return _parse_list(pos, base_indent)
        return _parse_dict(pos, base_indent)

    def _parse_dict(start_idx: int, dict_indent: int) -> tuple[dict[str, Any], int]:
        result: dict[str, Any] = {}
        cur = start_idx
        while True:
            cur = _next_meaningful(cur)
            if cur >= n:
                break
            line = _strip_comment(raw_lines[cur])
            ind = _indent_of(line)
            if ind < dict_indent:
                break
            if ind > dict_indent:
                raise ValueError(f"Unexpected indentation at line {cur + 1}: {raw_lines[cur]!r}")
            stripped = line.strip()
            if stripped.startswith("- ") or stripped == "-":
                break
            key, sep, rest = stripped.partition(":")
            if not sep:
                raise ValueError(f"Expected key: value at line {cur + 1}: {raw_lines[cur]!r}")
            key = key.strip().strip('"').strip("'")
            rest = rest.strip()
            cur += 1
            if rest in ("|", "|-", ">", ">-"):
                folded = rest.startswith(">")
                strip_trailing = rest.endswith("-")
                block_str, cur = _parse_block_scalar(cur, dict_indent, folded=folded)
                if strip_trailing:
                    block_str = block_str.rstrip("\n")
                result[key] = block_str
            elif rest == "":
                next_pos = _next_meaningful(cur)
                if next_pos < n and _indent_of(_strip_comment(raw_lines[next_pos])) > dict_indent:
                    child, cur = _parse_node(next_pos, dict_indent + 1)
                    result[key] = child
                else:
                    result[key] = None
            else:
                result[key] = _parse_scalar(rest)
        return result, cur

    def _parse_list(start_idx: int, list_indent: int) -> tuple[list[Any], int]:
        items: list[Any] = []
        cur = start_idx
        while True:
            cur = _next_meaningful(cur)
            if cur >= n:
                break
            line = _strip_comment(raw_lines[cur])
            ind = _indent_of(line)
            if ind < list_indent:
                break
            stripped = line.strip()
            if not (stripped.startswith("- ") or stripped == "-"):
                break
            after_dash = stripped[1:].strip()
            item_indent = ind + 2
            cur += 1
            if not after_dash:
                child, cur = _parse_node(cur, list_indent + 1)
                items.append(child)
            elif ":" in after_dash and not (
                after_dash.startswith('"') or after_dash.startswith("'")
            ):
                key, _, rest = after_dash.partition(":")
                key = key.strip().strip('"').strip("'")
                rest = rest.strip()
                item_dict: dict[str, Any] = {}
                if rest in ("|", "|-", ">", ">-"):
                    folded = rest.startswith(">")
                    strip_trailing = rest.endswith("-")
                    block_str, cur = _parse_block_scalar(cur, item_indent, folded=folded)
                    if strip_trailing:
                        block_str = block_str.rstrip("\n")
                    item_dict[key] = block_str
                elif rest == "":
                    next_pos = _next_meaningful(cur)
                    if next_pos < n and _indent_of(_strip_comment(raw_lines[next_pos])) > item_indent:
                        child, cur = _parse_node(next_pos, item_indent + 1)
                        item_dict[key] = child
                    else:
                        item_dict[key] = None
                else:
                    item_dict[key] = _parse_scalar(rest)

                next_pos = _next_meaningful(cur)
                if next_pos < n and _indent_of(_strip_comment(raw_lines[next_pos])) >= item_indent:
                    more_dict, cur = _parse_dict(next_pos, item_indent)
                    item_dict.update(more_dict)
                items.append(item_dict)
            else:
                items.append(_parse_scalar(after_dash))
        return items, cur

    parsed, _ = _parse_node(idx, 0)
    return parsed


def _stdlib_dump_yaml(data: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(data, dict):
        if not data:
            return "{}"
        lines: list[str] = []
        for k, v in data.items():
            if isinstance(v, str) and "\n" in v:
                lines.append(f"{prefix}{k}: |")
                for bline in v.rstrip("\n").splitlines():
                    lines.append(f"{prefix}  {bline}")
            elif isinstance(v, dict):
                if not v:
                    lines.append(f"{prefix}{k}: {{}}")
                else:
                    lines.append(f"{prefix}{k}:")
                    lines.append(_stdlib_dump_yaml(v, indent + 2))
            elif isinstance(v, list):
                if not v:
                    lines.append(f"{prefix}{k}: []")
                elif all(isinstance(x, (int, float)) for x in v):
                    lines.append(f"{prefix}{k}: {json.dumps(v)}")
                else:
                    lines.append(f"{prefix}{k}:")
                    lines.append(_stdlib_dump_yaml(v, indent + 2))
            else:
                lines.append(f"{prefix}{k}: {_format_scalar(v)}")
        return "\n".join(lines)
    if isinstance(data, list):
        if not data:
            return "[]"
        lines = []
        for item in data:
            if isinstance(item, dict):
                rendered = _stdlib_dump_yaml(item, indent + 2)
                rendered_lines = rendered.splitlines()
                first = rendered_lines[0].lstrip(" ")
                lines.append(f"{prefix}- {first}")
                lines.extend(rendered_lines[1:])
            else:
                lines.append(f"{prefix}- {_format_scalar(item)}")
        return "\n".join(lines)
    return f"{prefix}{_format_scalar(data)}"


def _format_scalar(val: Any) -> str:
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    return json.dumps(str(val))
