"""Pure utility functions — zero LLM and no app-runtime dependencies."""

from app.util.json import (
    DictMixin,
    compact_json,
    read_json,
    read_jsonl,
    to_jsonable,
    write_json,
    write_jsonl,
    write_text,
)
from app.util.action_types import (
    AGENT_ACTION_TYPES,
    CHOICE_ACTION_TYPES,
    DAY_INTERRUPT_ACTION_TYPES,
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
from app.util.time import (
    BEIJING_TZ,
    beijing_now,
    beijing_now_iso,
    beijing_now_str,
)
from app.util.winner import VALID_WINNERS, has_valid_winner, is_werewolf_win, normalize_winner
from app.config import DEFAULT_PATHS as DEFAULT, PathConfig
from app.util.callbacks import notify, observe, propagate_attributes, tracing_enabled

__all__ = [
    # json
    "DictMixin",
    "compact_json",
    "read_json",
    "read_jsonl",
    "to_jsonable",
    "write_json",
    "write_jsonl",
    "write_text",
    # action_types
    "AGENT_ACTION_TYPES",
    "CHOICE_ACTION_TYPES",
    "DAY_INTERRUPT_ACTION_TYPES",
    "EVENT_TYPE_SPEECH",
    "EVENT_TYPE_VOTE",
    "NIGHT_SKILL_ACTION_TYPES",
    "PUBLIC_SPEECH_EVENT_TYPES",
    "SHERIFF_ACTION_TYPES",
    "SPEECH_ACTION_TYPES",
    "TARGET_ACTION_TYPES",
    "VOTE_ACTION_TYPES",
    "VOTE_EVENT_TYPES",
    "is_valid_action_type",
    # time
    "BEIJING_TZ",
    "beijing_now",
    "beijing_now_iso",
    "beijing_now_str",
    # winner
    "VALID_WINNERS",
    "has_valid_winner",
    "is_werewolf_win",
    "normalize_winner",
    # paths
    "DEFAULT",
    "PathConfig",
    # callbacks
    "notify",
]
