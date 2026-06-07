from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Callable

from engine.models import ActionRequest, ActionResponse, ActionType

if TYPE_CHECKING:
    from engine.engine import GameEngine


ACTION_LABELS = {
    ActionType.SHERIFF_RUN: "上警选择",
    ActionType.SHERIFF_SPEAK: "警上发言",
    ActionType.SHERIFF_WITHDRAW: "退水选择",
    ActionType.SHERIFF_VOTE: "警长投票",
    ActionType.SHERIFF_BADGE: "警徽处理",
    ActionType.SPEECH_ORDER: "发言顺序",
    ActionType.GUARD_PROTECT: "守卫守护",
    ActionType.WEREWOLF_KILL: "狼人夜刀",
    ActionType.SEER_CHECK: "预言查验",
    ActionType.WITCH_ACT: "女巫行动",
    ActionType.LAST_WORD: "遗言",
    ActionType.SPEAK: "发言",
    ActionType.WHITE_WOLF_EXPLODE: "白狼王自爆",
    ActionType.EXILE_VOTE: "放逐投票",
    ActionType.PK_SPEAK: "对决发言",
    ActionType.PK_VOTE: "对决投票",
    ActionType.HUNTER_SHOOT: "猎人开枪",
}

CHOICE_LABELS = {
    "pass": "跳过",
    "skip": "跳过",
    "none": "不使用",
    "save": "使用解药",
    "antidote": "使用解药",
    "poison": "使用毒药",
    "burst": "发动自爆",
    "explode": "发动自爆",
    "shoot": "开枪",
    "run": "上警",
    "withdraw": "退水",
    "stay": "留警上",
    "transfer": "移交警徽",
    "destroy": "撕毁警徽",
    "forward": "顺序发言",
    "reverse": "逆序发言",
}


async def ask(
    engine: GameEngine,
    player_id: int,
    action_type: ActionType,
    candidates: tuple[int, ...] = (),
    metadata: dict | None = None,
    validator: Callable[[ActionResponse], bool] | None = None,
    default: ActionResponse | None = None,
) -> ActionResponse:
    default_response = sanitize_response_for_action(default or ActionResponse(action_type))
    validator = validator or (lambda response: response.action_type == action_type)
    for retry in range(2):
        request = ActionRequest(
            player_id=player_id,
            action_type=action_type,
            phase=engine.state.phase,
            observation=engine.observation_for(player_id, metadata),
            candidates=candidates,
            retry_count=retry,
            metadata=metadata or {},
        )
        engine._record(
            "action_request",
            message=f"请求{player_id}号执行{action_label(action_type)}",
            public=False,
            actor=player_id,
            payload={
                "action_type": action_type.value,
                "candidates": candidates,
                "metadata": metadata or {},
                "retry_count": retry,
            },
        )
        try:
            response = engine.agents[player_id].act(request)
            if inspect.isawaitable(response):
                response = await response
            response = sanitize_response_for_action(response)
        except Exception as exc:
            engine._record(
                "agent_error",
                message=f"{player_id}号执行{action_label(action_type)}失败，准备重试",
                public=False,
                actor=player_id,
                payload={
                    "action_type": action_type.value,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "retry_count": retry,
                },
            )
            continue
        if response.action_type == action_type and validator(response):
            engine._record(
                action_type.value,
                message=response.text,
                public=_is_public_action(action_type),
                actor=player_id,
                target=response.target,
                payload={
                    "choice": response.choice,
                    "decision_id": response.decision_id,
                },
            )
            engine._record(
                "action_response",
                message=response_message(player_id, response),
                public=False,
                actor=player_id,
                target=response.target,
                payload={
                    "action_type": response.action_type.value,
                    "choice": response.choice,
                    "text": response.text,
                    "decision_id": response.decision_id,
                },
            )
            return response
        engine._record(
            "invalid_response",
            message=f"{player_id} 号返回非法响应，准备重试",
            public=False,
            actor=player_id,
            target=getattr(response, "target", None),
            payload={
                "expected_action_type": action_type.value,
                "actual_action_type": getattr(getattr(response, "action_type", None), "value", None),
                "choice": getattr(response, "choice", None),
                "retry_count": retry,
            },
        )
    engine._record(
        "default_action",
        public=_is_public_action(action_type),
        actor=player_id,
        target=default_response.target,
        payload={"action_type": action_type.value, "choice": default_response.choice},
    )
    engine._record(
        "default_action",
        message=f"{player_id} 号连续非法响应，使用默认动作",
        public=False,
        actor=player_id,
        target=default_response.target,
        payload={"action_type": action_type.value, "choice": default_response.choice},
    )
    return default_response


def response_message(player_id: int, response: ActionResponse) -> str:
    response = sanitize_response_for_action(response)
    parts = [f"{player_id}号响应{action_label(response.action_type)}"]
    if response.target is not None:
        parts.append(f"目标{response.target}号")
    if response.choice is not None:
        parts.append(f"选择{choice_label(response.choice)}")
    if response.text:
        parts.append(f"{text_label(response.action_type)}：{response.text}")
    return "，".join(parts)


def action_label(action_type: ActionType) -> str:
    return ACTION_LABELS.get(action_type, "行动")


def choice_label(choice: str) -> str:
    return CHOICE_LABELS.get(str(choice), str(choice))


def text_label(action_type: ActionType) -> str:
    if action_type in _SPEECH_TEXT_ACTION_TYPES:
        return "发言"
    if action_type in {
        ActionType.SHERIFF_VOTE,
        ActionType.EXILE_VOTE,
        ActionType.PK_VOTE,
    }:
        return "理由"
    return "决策说明"


_SPEECH_TEXT_ACTION_TYPES = {
    ActionType.SPEAK,
    ActionType.SHERIFF_SPEAK,
    ActionType.PK_SPEAK,
    ActionType.LAST_WORD,
}


def sanitize_response_for_action(response: ActionResponse) -> ActionResponse:
    if response.action_type not in _SPEECH_TEXT_ACTION_TYPES:
        return response
    if response.target is None and response.choice is None:
        return response
    return ActionResponse(
        action_type=response.action_type,
        text=response.text,
        decision_id=response.decision_id,
    )


_PRIVATE_ACTION_TYPES = {
    ActionType.GUARD_PROTECT,
    ActionType.WEREWOLF_KILL,
    ActionType.SEER_CHECK,
    ActionType.WITCH_ACT,
}


def _is_public_action(action_type: ActionType) -> bool:
    return action_type not in _PRIVATE_ACTION_TYPES
