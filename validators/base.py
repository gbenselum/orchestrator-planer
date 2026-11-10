"""Base types and protocols for deterministic verification modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationResult:
    """Deterministic validation outcome returned by any assertion module."""

    passed: bool
    validator_name: str
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> str:
        if self.passed:
            return f"[{self.validator_name}] PASS"
        return f"[{self.validator_name}] FAIL: " + "; ".join(self.errors)
