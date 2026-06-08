"""LangChain services — all LLM capability components.

Only services/chain.py calls the LLM directly.
"""

from app.services.llm import (
    create_llm,
    load_llm_client,
)
from app.services.memory import (
    AgentMemory,
    CompressedSegmentSummary,
    Segment,
    SegmentEvent,
    normalize_phase_group,
)
from app.services.prompt import (
    MarkdownSkill,
    SkillIndex,
    SkillLoadDiagnostic,
    SkillLoadReport,
    action_instruction,
    build_decision_prompt_template,
    check_skill_limits,
    configure_skill_root,
    DecisionOutput,
    format_memory_messages,
    format_skill_context,
    load_markdown_skill_diagnostics,
    load_markdown_skill_report,
    load_markdown_skills,
    parse_front_matter,
    select_skills,
    validate_runtime_body,
)
from app.services.chain import (
    build_apply_chain,
    build_compress_chain,
    build_consolidate_chain,
    build_decision_chain,
    build_evidence_chain,
    build_raw_message_chain,
    create_apply_chain,
    create_consolidate_chain,
    create_decision_chain,
    create_evidence_chain,
    run_apply_chain,
    run_compress_chain,
    run_consolidate_chain,
    run_decision_chain,
    run_evidence_chain,
)
from app.services import tool

__all__ = [
    # llm
    "create_llm",
    "load_llm_client",
    # memory
    "AgentMemory",
    "CompressedSegmentSummary",
    "Segment",
    "SegmentEvent",
    "normalize_phase_group",
    # prompt
    "MarkdownSkill",
    "SkillIndex",
    "SkillLoadDiagnostic",
    "SkillLoadReport",
    "action_instruction",
    "build_decision_prompt_template",
    "check_skill_limits",
    "configure_skill_root",
    "DecisionOutput",
    "format_memory_messages",
    "format_skill_context",
    "load_markdown_skill_diagnostics",
    "load_markdown_skill_report",
    "load_markdown_skills",
    "parse_front_matter",
    "select_skills",
    "validate_runtime_body",
    # chain
    "build_apply_chain",
    "build_compress_chain",
    "build_consolidate_chain",
    "build_decision_chain",
    "build_evidence_chain",
    "build_raw_message_chain",
    "create_apply_chain",
    "create_consolidate_chain",
    "create_decision_chain",
    "create_evidence_chain",
    "run_apply_chain",
    "run_compress_chain",
    "run_consolidate_chain",
    "run_decision_chain",
    "run_evidence_chain",
    # tool
    "tool",
]
