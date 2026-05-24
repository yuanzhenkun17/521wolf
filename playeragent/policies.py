from __future__ import annotations

from werewolf.models import ActionRequest, ActionResponse, ActionType


SPEECH_ACTIONS = {
    ActionType.SHERIFF_SPEAK,
    ActionType.LAST_WORD,
    ActionType.SPEAK,
    ActionType.PK_SPEAK,
}

TARGET_ACTIONS = {
    ActionType.SHERIFF_VOTE,
    ActionType.GUARD_PROTECT,
    ActionType.WEREWOLF_KILL,
    ActionType.SEER_CHECK,
    ActionType.EXILE_VOTE,
    ActionType.PK_VOTE,
    ActionType.HUNTER_SHOOT,
}


def apply_response_policy(request: ActionRequest, response: ActionResponse) -> ActionResponse:
    if response.target is not None and request.candidates and response.target not in request.candidates:
        return fallback_response(request)
    if request.action_type is ActionType.SHERIFF_WITHDRAW and response.choice == "withdraw":
        remaining_runners = request.metadata.get("remaining_runners") or request.metadata.get("runners")
        if remaining_runners is None:
            remaining_runners = list(request.candidates)
        if remaining_runners == [request.player_id]:
            return ActionResponse(request.action_type, choice="stay", text=response.text)
    return response


def fallback_response(request: ActionRequest) -> ActionResponse:
    if request.action_type in SPEECH_ACTIONS:
        return ActionResponse(request.action_type, text=f"{request.player_id}号玩家发言：先过。")
    if request.action_type == ActionType.SHERIFF_RUN:
        return ActionResponse(request.action_type, choice="pass")
    if request.action_type == ActionType.SHERIFF_WITHDRAW:
        return ActionResponse(request.action_type, choice="stay")
    if request.action_type == ActionType.SHERIFF_BADGE:
        if request.candidates:
            return ActionResponse(request.action_type, choice="transfer", target=request.candidates[0])
        return ActionResponse(request.action_type, choice="destroy")
    if request.action_type == ActionType.SPEECH_ORDER:
        return ActionResponse(request.action_type, choice="forward")
    if request.action_type == ActionType.WITCH_ACT:
        return ActionResponse(request.action_type, choice="none")
    if request.action_type == ActionType.WHITE_WOLF_EXPLODE:
        return ActionResponse(request.action_type, choice="pass")
    if request.action_type in TARGET_ACTIONS:
        target = request.candidates[0] if request.candidates else None
        return ActionResponse(request.action_type, target=target)
    return ActionResponse(request.action_type)
