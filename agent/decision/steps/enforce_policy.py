from __future__ import annotations

from agent.infrastructure.tracing import observe
from dataclasses import dataclass
from typing import Any

from engine.models import ActionRequest, ActionResponse, ActionType

from agent.core.context import AgentContext


# action classification
_SPEECH_ACTIONS = {
    ActionType.SHERIFF_SPEAK,
    ActionType.LAST_WORD,
    ActionType.SPEAK,
    ActionType.PK_SPEAK,
}

# Used only by _fallback_response — validation is done via _ACTION_VALIDATORS
_TARGET_ACTIONS = {
    ActionType.SHERIFF_VOTE,
    ActionType.GUARD_PROTECT,
    ActionType.WEREWOLF_KILL,
    ActionType.SEER_CHECK,
    ActionType.EXILE_VOTE,
    ActionType.PK_VOTE,
    ActionType.HUNTER_SHOOT,
}

# Per-ActionType valid choice values
_VALID_CHOICES: dict[ActionType, set[str | None]] = {
    ActionType.SHERIFF_RUN: {"run", "pass"},
    ActionType.SHERIFF_WITHDRAW: {"stay", "withdraw"},
    ActionType.SHERIFF_BADGE: {"transfer", "destroy"},
    ActionType.SPEECH_ORDER: {"forward", "reverse"},
    ActionType.WITCH_ACT: {"save", "poison", "none"},
    ActionType.WHITE_WOLF_EXPLODE: {"pass", "explode"},
}


# per-action validators
@dataclass(slots=True)
class ValidationResult:
    valid: bool
    repairable: bool = False
    reason: str = ""


def _validate_witch_act(request: ActionRequest, response: ActionResponse) -> ValidationResult:
    if response.choice == "none":
        return ValidationResult(True)
    if response.choice == "save":
        if not request.metadata.get("can_save", False):
            return ValidationResult(False, reason="save not available this round")
        return ValidationResult(True)
    if response.choice == "poison":
        if not request.metadata.get("can_poison", False):
            return ValidationResult(False, reason="poison not available this round")
        if response.target is None:
            return ValidationResult(False, reason="poison requires a target")
        if request.candidates and response.target not in request.candidates:
            return ValidationResult(False, repairable=True, reason="poison target not in candidates")
        return ValidationResult(True)
    return ValidationResult(False, reason="invalid witch choice")


def _validate_sheriff_badge(request: ActionRequest, response: ActionResponse) -> ValidationResult:
    if response.choice == "destroy":
        return ValidationResult(True)
    if response.choice == "transfer":
        if response.target is None:
            return ValidationResult(False, reason="transfer requires a target")
        if request.candidates and response.target not in request.candidates:
            return ValidationResult(False, repairable=True, reason="transfer target not in candidates")
        return ValidationResult(True)
    return ValidationResult(False, reason="invalid badge choice")


def _validate_white_wolf_explode(request: ActionRequest, response: ActionResponse) -> ValidationResult:
    """White wolf king explode validation — matches rules engine expectations.

    Valid states:
    - ``target in candidates`` — explode with that target
    - ``target is None and choice in ("pass", None)`` — skip explosion
    All other combinations are invalid and trigger fallback to pass.
    """
    if response.target is not None and response.target in request.candidates:
        return ValidationResult(True)
    if response.target is None and response.choice in {"pass", None}:
        return ValidationResult(True)
    return ValidationResult(False, reason="invalid explode state")


def _validate_target_action(request: ActionRequest, response: ActionResponse) -> ValidationResult:
    """Generic validator: target must be in candidates if provided."""
    if response.target is not None and request.candidates and response.target not in request.candidates:
        return ValidationResult(False, repairable=True, reason="target not in candidates")
    return ValidationResult(True)


_ACTION_VALIDATORS: dict[ActionType, Any] = {
    ActionType.WITCH_ACT: _validate_witch_act,
    ActionType.SHERIFF_BADGE: _validate_sheriff_badge,
    ActionType.WHITE_WOLF_EXPLODE: _validate_white_wolf_explode,
    ActionType.SHERIFF_VOTE: _validate_target_action,
    ActionType.GUARD_PROTECT: _validate_target_action,
    ActionType.WEREWOLF_KILL: _validate_target_action,
    ActionType.SEER_CHECK: _validate_target_action,
    ActionType.EXILE_VOTE: _validate_target_action,
    ActionType.PK_VOTE: _validate_target_action,
    ActionType.HUNTER_SHOOT: _validate_target_action,
}


# main node
@observe(name="enforce_policy_step")
def enforce_policy_step(ctx: AgentContext) -> AgentContext:
    """Validate and correct the parsed response.

    Guarantees a legal ``ActionResponse`` in all cases.  The strategy:

    1. If a response exists, try to **repair** minor issues (invalid choice,
       invalid target, missing target for poison/transfer).
    2. If repair is impossible, **fall back** to a safe default.
    3. If no response exists at all, fall back immediately.

    Every adjustment is recorded in ``ctx.policy_adjustments`` and the final
    outcome is reflected in ``ctx.source``.
    """
    request = ctx.request

    if ctx.response is None:
        ctx.response = _fallback_response(request, ctx)
        ctx.source = "fallback"
        ctx.policy_adjustments.append("No parsed response available; used fallback.")
        return ctx

    response = ctx.response
    adjustments: list[str] = []

    # -- validate choice -------------------------------------------------------
    valid_choices = _VALID_CHOICES.get(request.action_type)
    if valid_choices is not None and response.choice not in valid_choices:
        old_choice = response.choice
        response = ActionResponse(
            request.action_type,
            target=response.target,
            choice=_default_choice(request.action_type),
            text=response.text,
        )
        adjustments.append(
            f"Invalid choice {old_choice!r} for {request.action_type.value}; "
            f"repaired to {response.choice!r}."
        )

    # -- per-action validation -------------------------------------------------
    validator = _ACTION_VALIDATORS.get(request.action_type)
    if validator is not None:
        result = validator(request, response)
        if not result.valid:
            if result.repairable:
                repaired = _pick_best_target(request, ctx)
                if repaired is not None:
                    old_target = response.target
                    response = ActionResponse(
                        request.action_type,
                        target=repaired,
                        choice=response.choice,
                        text=response.text,
                    )
                    adjustments.append(
                        f"{result.reason}; repaired target from {old_target} to {repaired}."
                    )
                else:
                    adjustments.append(f"{result.reason}; no repair available, falling back.")
                    ctx.response = _fallback_response(request, ctx)
                    ctx.source = "fallback"
                    ctx.policy_adjustments.extend(adjustments)
                    return ctx
            else:
                adjustments.append(f"{result.reason}; falling back.")
                ctx.response = _fallback_response(request, ctx)
                ctx.source = "fallback"
                ctx.policy_adjustments.extend(adjustments)
                return ctx

    # -- sheriff withdraw: last runner must stay --------------------------------
    if request.action_type is ActionType.SHERIFF_WITHDRAW and response.choice == "withdraw":
        remaining = request.metadata.get("remaining_runners") or request.metadata.get("runners")
        if remaining is None:
            remaining = list(request.candidates)
        if remaining == [request.player_id]:
            response = ActionResponse(request.action_type, choice="stay", text=response.text)
            adjustments.append("Last sheriff runner attempted to withdraw; forced stay.")

    # -- determine final source ------------------------------------------------
    ctx.response = response
    if adjustments:
        ctx.source = "policy_adjusted"
        ctx.policy_adjustments.extend(adjustments)
    elif ctx.source == "llm":
        ctx.source = "tot" if ctx.tot_enabled else "llm"

    return ctx


# helpers
def _default_choice(action_type: ActionType) -> str | None:
    defaults = {
        ActionType.SHERIFF_RUN: "pass",
        ActionType.SHERIFF_WITHDRAW: "stay",
        ActionType.SHERIFF_BADGE: "destroy",
        ActionType.SPEECH_ORDER: "forward",
        ActionType.WITCH_ACT: "none",
        ActionType.WHITE_WOLF_EXPLODE: "pass",
    }
    return defaults.get(action_type)


def _pick_best_target(request: ActionRequest, ctx: AgentContext) -> int | None:
    """Use belief context to pick the best candidate, falling back to first."""
    candidates = list(request.candidates)
    if not candidates:
        return None
    belief = ctx.belief_context
    top_suspicions = belief.get("top_suspicions", [])
    for entry in top_suspicions:
        pid = entry.get("player_id")
        if pid in candidates:
            return pid
    return candidates[0]


def _fallback_response(request: ActionRequest, ctx: AgentContext) -> ActionResponse:
    """Generate a guaranteed-legal fallback response for any action type."""
    if request.action_type in _SPEECH_ACTIONS:
        return ActionResponse(
            request.action_type,
            text=f"{request.player_id}号玩家发言：先过。",
        )
    if request.action_type == ActionType.SHERIFF_RUN:
        return ActionResponse(request.action_type, choice="pass")
    if request.action_type == ActionType.SHERIFF_WITHDRAW:
        return ActionResponse(request.action_type, choice="stay")
    if request.action_type == ActionType.SHERIFF_BADGE:
        if request.candidates:
            return ActionResponse(
                request.action_type,
                choice="transfer",
                target=request.candidates[0],
            )
        return ActionResponse(request.action_type, choice="destroy")
    if request.action_type == ActionType.SPEECH_ORDER:
        return ActionResponse(request.action_type, choice="forward")
    if request.action_type == ActionType.WITCH_ACT:
        return ActionResponse(request.action_type, choice="none")
    if request.action_type == ActionType.WHITE_WOLF_EXPLODE:
        return ActionResponse(request.action_type, choice="pass")
    if request.action_type in _TARGET_ACTIONS:
        target = _pick_best_target(request, ctx)
        return ActionResponse(request.action_type, target=target)
    return ActionResponse(request.action_type)
