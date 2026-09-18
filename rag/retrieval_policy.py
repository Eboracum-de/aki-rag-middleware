"""Bounded retrieval-policy configuration for the shared middleware.

The policy decides which implemented capabilities are mandatory, optional for
planner selection, or disabled.  It is deliberately *not* a workflow language:
round counts, candidate budgets and execution mechanics remain deterministic
configuration elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

_INTERNAL_ARMS = ("files", "vector", "graph")
_ARM_MODES = {"required", "optional", "disabled"}
_WEB_MODES = {"disabled", "explicit", "planner"}



def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def configured_internal_arms(config: dict[str, Any] | None) -> set[str]:
    cfg = config or {}
    arms: set[str] = set()
    if _truthy((cfg.get("elasticsearch") or {}).get("enabled"), True):
        arms.add("files")
    if _truthy((cfg.get("qdrant") or {}).get("enabled"), True):
        arms.add("vector")
    if _truthy((cfg.get("neo4j") or {}).get("enabled"), False) and _truthy(
        (cfg.get("graph_retrieval") or {}).get("enabled"), True
    ):
        arms.add("graph")
    return arms

def _mode(value: Any, default: str) -> str:
    text = str(value or default).strip().casefold()
    return text


@dataclass(frozen=True)
class RetrievalPolicy:
    files: str = "optional"
    vector: str = "optional"
    graph: str = "optional"
    optional_default: str = "include"  # include | exclude
    web: str = "planner"               # disabled | explicit | planner

    def mode_for(self, arm: str) -> str:
        return str(getattr(self, arm))

    @property
    def required_arms(self) -> set[str]:
        return {arm for arm in _INTERNAL_ARMS if self.mode_for(arm) == "required"}

    @property
    def optional_arms(self) -> set[str]:
        return {arm for arm in _INTERNAL_ARMS if self.mode_for(arm) == "optional"}

    @property
    def disabled_arms(self) -> set[str]:
        return {arm for arm in _INTERNAL_ARMS if self.mode_for(arm) == "disabled"}

    @property
    def allowed_arms(self) -> set[str]:
        return self.required_arms | self.optional_arms

    def available_allowed_arms(self, available: Iterable[str]) -> set[str]:
        return self.allowed_arms & {str(value).strip().casefold() for value in available}

    def fallback_arms(self, available: Iterable[str] | None = None) -> set[str]:
        allowed = set(self.allowed_arms)
        required = set(self.required_arms)
        optional = set(self.optional_arms)
        if available is not None:
            available_set = {str(value).strip().casefold() for value in available}
            allowed &= available_set
            required &= available_set
            optional &= available_set
        if self.optional_default == "exclude":
            return required
        return required | optional

    def planner_arms(
        self,
        requested: Iterable[str] | None,
        *,
        valid: bool = True,
        available: Iterable[str] | None = None,
    ) -> set[str]:
        """Resolve a planner choice without allowing it to drop required arms.

        A failed/malformed planner decision falls back deterministically.  A
        valid decision may omit optional arms but cannot enable disabled ones.
        """
        available_set = None if available is None else {str(value).strip().casefold() for value in available}
        if not valid or requested is None:
            return self.fallback_arms(available_set)
        selected = {str(value).strip().casefold() for value in requested if str(value).strip()}
        required = set(self.required_arms)
        optional = set(self.optional_arms)
        if available_set is not None:
            required &= available_set
            optional &= available_set
        selected &= optional
        resolved = required | selected
        # Normal retrieval must keep at least one internal document arm. A
        # genuine web-only request has its own explicit workflow.
        return resolved or self.fallback_arms(available_set)


def load_retrieval_policy(config: dict[str, Any] | None) -> RetrievalPolicy:
    raw = dict((config or {}).get("retrieval_policy") or {})
    internal = dict(raw.get("internal") or {})
    values = {
        "files": _mode(internal.get("files"), "optional"),
        "vector": _mode(internal.get("vector"), "optional"),
        "graph": _mode(internal.get("graph"), "optional"),
        "optional_default": _mode(raw.get("optional_default"), "include"),
        "web": _mode(raw.get("web"), "planner"),
    }
    for arm in _INTERNAL_ARMS:
        if values[arm] not in _ARM_MODES:
            raise ValueError(f"retrieval_policy.internal.{arm} must be required, optional or disabled")
    if values["optional_default"] not in {"include", "exclude"}:
        raise ValueError("retrieval_policy.optional_default must be include or exclude")
    if values["web"] not in _WEB_MODES:
        raise ValueError("retrieval_policy.web must be disabled, explicit or planner")
    return RetrievalPolicy(**values)
