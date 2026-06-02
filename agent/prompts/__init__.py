# Shim — re-exports from prompts/base.py and prompts/formatting.py
from agent.prompts.base import (  # noqa: F401
    build_messages,
    build_system_prompt,
    build_request_prompt,
)
from agent.prompts.formatting import format_field_notes  # noqa: F401
