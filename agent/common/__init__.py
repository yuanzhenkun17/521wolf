"""Small shared helpers with no agent-domain dependencies."""

from agent.common.action_types import (
    AGENT_ACTION_TYPES,
    CHOICE_ACTION_TYPES,
    EVENT_TYPE_SPEECH,
    EVENT_TYPE_VOTE,
    NIGHT_SKILL_ACTION_TYPES,
    PUBLIC_SPEECH_EVENT_TYPES,
    SHERIFF_ACTION_TYPES,
    SPEECH_ACTION_TYPES,
    TARGET_ACTION_TYPES,
    VOTE_ACTION_TYPES,
    VOTE_EVENT_TYPES,
    is_valid_action_type,
)
from agent.common.callbacks import notify
from agent.common.coercion import as_float, as_int_list
from agent.common.json import (
    DictMixin,
    compact_json,
    read_json,
    read_jsonl,
    to_jsonable,
    write_json,
    write_jsonl,
    write_text,
)
from agent.common.paths import PathConfig
from agent.common.time import beijing_now_iso, beijing_now_str
from agent.common.winner import is_werewolf_win

__all__ = [
    "AGENT_ACTION_TYPES",
    "as_float",
    "as_int_list",
    "beijing_now_iso",
    "beijing_now_str",
    "CHOICE_ACTION_TYPES",
    "compact_json",
    "DictMixin",
    "EVENT_TYPE_SPEECH",
    "EVENT_TYPE_VOTE",
    "is_valid_action_type",
    "is_werewolf_win",
    "NIGHT_SKILL_ACTION_TYPES",
    "notify",
    "PathConfig",
    "PUBLIC_SPEECH_EVENT_TYPES",
    "read_json",
    "read_jsonl",
    "SHERIFF_ACTION_TYPES",
    "SPEECH_ACTION_TYPES",
    "TARGET_ACTION_TYPES",
    "to_jsonable",
    "VOTE_ACTION_TYPES",
    "VOTE_EVENT_TYPES",
    "write_json",
    "write_jsonl",
    "write_text",
]
