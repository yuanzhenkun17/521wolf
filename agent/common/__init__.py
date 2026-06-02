"""Small shared helpers with no agent-domain dependencies."""

from agent.common.callbacks import notify
from agent.common.coercion import as_float, as_int_list
from agent.common.json import compact_json, write_json
from agent.common.paths import PathConfig
from agent.common.time import beijing_now_iso, beijing_now_str
from agent.common.winner import is_werewolf_win

__all__ = [
    "as_float",
    "as_int_list",
    "beijing_now_iso",
    "beijing_now_str",
    "compact_json",
    "is_werewolf_win",
    "notify",
    "PathConfig",
    "write_json",
]
