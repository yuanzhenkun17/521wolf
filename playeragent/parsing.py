from __future__ import annotations

import json
import re
from typing import Any

from werewolf.models import ActionRequest, ActionResponse

from playeragent.decision import DecisionRecord


def parse_action_response(request: ActionRequest, content: str) -> ActionResponse:
    data = load_json_object(content)
    choice = data.get("choice")
    target = data.get("target")
    text = str(data.get("text") or "")
    if target is not None:
        target = int(target)
    return ActionResponse(request.action_type, target=target, choice=choice, text=text)


def parse_decision_record(request: ActionRequest, content: str, response: ActionResponse) -> DecisionRecord:
    try:
        data = load_json_object(content)
    except json.JSONDecodeError:
        data = {}
    return DecisionRecord(
        action_type=request.action_type,
        day=request.observation.day,
        phase=request.phase.value,
        player_id=request.player_id,
        role=request.observation.self_role.value,
        candidates=list(request.candidates),
        selected_target=response.target,
        selected_choice=response.choice,
        public_text=response.text,
        private_reasoning=str(data.get("reasoning") or ""),
        alternatives=_int_list(data.get("alternatives")),
        rejected_reasons=[str(item) for item in data.get("rejected_reasons", []) if item is not None],
    )


def load_json_object(content: str) -> dict:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def _int_list(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result
