from __future__ import annotations

from agent.infrastructure.tracing import observe
from typing import Any

from engine.models import ActionRequest, ActionResponse, ActionType

from agent.common.action_types import (
    CHOICE_ACTION_TYPES,
    SPEECH_ACTION_TYPES,
    TARGET_ACTION_TYPES,
)
from agent.core.context import AgentContext


# action classification — derived from centralized definitions
# (enum sets for per-request validation; string sets for dict-based
#  lookups are in agent.common.action_types)
_SPEECH_ACTIONS: frozenset[ActionType] = frozenset({
    ActionType.SPEAK,
    ActionType.SHERIFF_SPEAK,
    ActionType.PK_SPEAK,
    ActionType.LAST_WORD,
})

_TARGET_ACTIONS: frozenset[ActionType] = frozenset({
    ActionType.SHERIFF_VOTE,
    ActionType.GUARD_PROTECT,
    ActionType.WEREWOLF_KILL,
    ActionType.SEER_CHECK,
    ActionType.EXILE_VOTE,
    ActionType.PK_VOTE,
    ActionType.HUNTER_SHOOT,
})

# Per-ActionType valid choice values
_VALID_CHOICES: dict[ActionType, set[str | None]] = {
    ActionType.SHERIFF_RUN: {"run", "pass"},
    ActionType.SHERIFF_WITHDRAW: {"stay", "withdraw"},
    ActionType.SHERIFF_BADGE: {"transfer", "destroy"},
    ActionType.SPEECH_ORDER: {"forward", "reverse"},
    ActionType.WITCH_ACT: {"save", "poison", "none"},
    ActionType.WHITE_WOLF_EXPLODE: {"pass", "explode"},
}


# per-action validators — return None if valid, or a reason string if invalid


def _validate_witch_act(request: ActionRequest, response: ActionResponse) -> str | None:
    if response.choice == "none":
        return None
    if response.choice == "save":
        if not request.metadata.get("can_save", False):
            return "save not available this round"
        return None
    if response.choice == "poison":
        if not request.metadata.get("can_poison", False):
            return "poison not available this round"
        if response.target is None:
            return "poison requires a target"
        if request.candidates and response.target not in request.candidates:
            return "poison target not in candidates"
        return None
    return "invalid witch choice"


def _validate_sheriff_badge(request: ActionRequest, response: ActionResponse) -> str | None:
    if response.choice == "destroy":
        return None
    if response.choice == "transfer":
        if response.target is None:
            return "transfer requires a target"
        if request.candidates and response.target not in request.candidates:
            return "transfer target not in candidates"
        return None
    return "invalid badge choice"


def _validate_white_wolf_explode(request: ActionRequest, response: ActionResponse) -> str | None:
    """White wolf king explode validation — matches rules engine expectations.

    Valid states:
    - ``target in candidates`` — explode with that target
    - ``target is None and choice in ("pass", None)`` — skip explosion
    All other combinations are invalid and trigger fallback to pass.
    """
    if response.target is not None and response.target in request.candidates:
        return None
    if response.target is None and response.choice in {"pass", None}:
        return None
    return "invalid explode state"


def _validate_target_action(request: ActionRequest, response: ActionResponse) -> str | None:
    """Generic validator: target must be in candidates if provided."""
    if response.target is not None and request.candidates and response.target not in request.candidates:
        return "target not in candidates"
    return None


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
        ctx.response = _fallback_response(request)
        if ctx.source != "llm_error":
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
        reason = validator(request, response)
        if reason is not None:
            if "not in candidates" in reason:
                repaired = request.candidates[0] if request.candidates else None
                if repaired is not None:
                    old_target = response.target
                    response = ActionResponse(
                        request.action_type,
                        target=repaired,
                        choice=response.choice,
                        text=response.text,
                    )
                    adjustments.append(
                        f"{reason}; repaired target from {old_target} to {repaired}."
                    )
                else:
                    adjustments.append(f"{reason}; no repair available, falling back.")
                    ctx.response = _fallback_response(request)
                    ctx.source = "fallback"
                    ctx.policy_adjustments.extend(adjustments)
                    return ctx
            else:
                adjustments.append(f"{reason}; falling back.")
                ctx.response = _fallback_response(request)
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


def _fallback_response(request: ActionRequest) -> ActionResponse:
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
        target = request.candidates[0] if request.candidates else None
        return ActionResponse(request.action_type, target=target)
    return ActionResponse(request.action_type)
