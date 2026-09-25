"""Stable policy/inspection hook contract.

0.8.6-rc1.1 wires these stages into the relevant data-flow boundaries but ships
no configured policy evaluator. With no evaluator installed every hook is a
no-op ALLOW decision, preserving the pre-hook runtime behaviour.

A later configuration layer can install one evaluator that delegates to malware,
URL-policy, ICAP/YARA/DLP/redaction or site-specific adapters without changing
the calling data paths again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping


ALLOW = "ALLOW"
BLOCK = "BLOCK"
QUARANTINE = "QUARANTINE"
MODIFY = "MODIFY"

OUTBOUND_QUERY = "outbound_query"
PRE_FETCH = "pre_fetch"
POST_FETCH = "post_fetch"
PRE_PERSIST = "pre_persist"
PRE_MODEL_EGRESS = "pre_model_egress"

HOOK_STAGES = frozenset(
    {
        OUTBOUND_QUERY,
        PRE_FETCH,
        POST_FETCH,
        PRE_PERSIST,
        PRE_MODEL_EGRESS,
    }
)
HOOK_ACTIONS = frozenset({ALLOW, BLOCK, QUARANTINE, MODIFY})


@dataclass(frozen=True)
class PolicyHookRequest:
    stage: str
    content: Any = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PolicyHookDecision:
    action: str = ALLOW
    content: Any = None
    reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)


class PolicyHookRejected(RuntimeError):
    """A configured policy hook blocked or quarantined an operation."""

    def __init__(self, stage: str, action: str, reason: str = ""):
        self.stage = stage
        self.action = action
        self.reason = reason
        detail = f"policy hook {stage} returned {action}"
        if reason:
            detail += f": {reason}"
        super().__init__(detail)


PolicyEvaluator = Callable[[PolicyHookRequest], PolicyHookDecision]
_evaluator: PolicyEvaluator | None = None


def install_policy_evaluator(evaluator: PolicyEvaluator | None) -> None:
    """Install the process-local evaluator.

    Startup/configuration code may install an adapter later. Passing None restores
    the shipped ALLOW-only behaviour.
    """

    global _evaluator
    _evaluator = evaluator


def reset_policy_evaluator() -> None:
    install_policy_evaluator(None)


def evaluate_policy_hook(
    stage: str,
    *,
    content: Any = None,
    metadata: Mapping[str, Any] | None = None,
) -> PolicyHookDecision:
    """Evaluate one hook stage.

    No evaluator is configured in rc1.1, so the default is deliberately ALLOW.
    Exceptions raised by a configured evaluator are not swallowed: a required
    inspection service can therefore fail closed simply by failing the operation.
    """

    stage = str(stage or "").strip()
    if stage not in HOOK_STAGES:
        raise ValueError(f"unknown policy hook stage: {stage!r}")

    request = PolicyHookRequest(
        stage=stage,
        content=content,
        metadata=dict(metadata or {}),
    )
    evaluator = _evaluator
    if evaluator is None:
        return PolicyHookDecision(action=ALLOW, content=content)

    decision = evaluator(request)
    if not isinstance(decision, PolicyHookDecision):
        raise TypeError("policy evaluator must return PolicyHookDecision")

    action = str(decision.action or "").strip().upper()
    if action not in HOOK_ACTIONS:
        raise ValueError(f"unknown policy hook action: {decision.action!r}")

    return PolicyHookDecision(
        action=action,
        content=decision.content,
        reason=str(decision.reason or ""),
        metadata=dict(decision.metadata or {}),
    )


def apply_policy_hook(
    stage: str,
    *,
    content: Any = None,
    metadata: Mapping[str, Any] | None = None,
) -> Any:
    """Apply one hook and return the permitted/transformed content."""

    decision = evaluate_policy_hook(stage, content=content, metadata=metadata)
    if decision.action in {BLOCK, QUARANTINE}:
        raise PolicyHookRejected(stage, decision.action, decision.reason)
    if decision.action == MODIFY:
        return decision.content
    return content
