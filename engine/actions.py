from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Callable

from engine.models import ActionRequest, ActionResponse, ActionType

if TYPE_CHECKING:
    from engine.engine import GameEngine


async def ask(
    engine: GameEngine,
    player_id: int,
    action_type: ActionType,
    candidates: tuple[int, ...] = (),
    metadata: dict | None = None,
    validator: Callable[[ActionResponse], bool] | None = None,
    default: ActionResponse | None = None,
) -> ActionResponse:
    default_response = default or ActionResponse(action_type)
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
            message=f"请求 {player_id} 号执行 {action_type.value}",
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
        except Exception as exc:
            engine._record(
                "agent_error",
                message=f"{player_id} 号执行 {action_type.value} 失败，准备重试",
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
    parts = [f"{player_id} 号响应 {response.action_type.value}"]
    if response.target is not None:
        parts.append(f"目标 {response.target} 号")
    if response.choice is not None:
        parts.append(f"选择 {response.choice}")
    if response.text:
        parts.append(f"{text_label(response.action_type)}：{response.text}")
    return "，".join(parts)


def text_label(action_type: ActionType) -> str:
    if action_type in {
        ActionType.SPEAK,
        ActionType.SHERIFF_SPEAK,
        ActionType.PK_SPEAK,
        ActionType.LAST_WORD,
    }:
        return "发言"
    if action_type in {
        ActionType.SHERIFF_VOTE,
        ActionType.EXILE_VOTE,
        ActionType.PK_VOTE,
    }:
        return "理由"
    return "决策说明"
