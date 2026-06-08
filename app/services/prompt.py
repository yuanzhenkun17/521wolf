"""Prompt construction for the app runtime.

Uses LangChain ChatPromptTemplate for structured prompts + pydantic
DecisionOutput for structured parsing.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from engine import ActionRequest, ActionType, Role

from app.config import PROMPT_DEFAULT_MAX_MESSAGE_CHARS, PROMPT_DEFAULT_MAX_TOTAL_CHARS
from app.services.memory import AgentMemory
from app.util.text import (
    extract_json,
    parse_yaml_front_matter,
    coerce_value,
    split_markdown_sections,
)

_log = logging.getLogger(__name__)


# ===========================================================================
# Structured output — pydantic DecisionOutput
# ===========================================================================

from pydantic import BaseModel, Field as PydanticField


class DecisionOutput(BaseModel):
    """Structured decision output for the agent pipeline."""
    schema_version: str = PydanticField("1.0", description="LLM output schema version")
    choice: str | None = PydanticField(None, description="The action choice, or None if N/A")
    target: int | None = PydanticField(None, description="Target player seat number, or None")
    public_text: str = PydanticField("", description="Public speech text visible to all players")
    private_reasoning: str = PydanticField("", description="Private internal reasoning (hidden)")
    confidence: float = PydanticField(0.5, ge=0.0, le=1.0, description="Confidence score 0.0-1.0")
    alternatives: list[int] = PydanticField(default_factory=list, description="Alternative targets considered")
    rejected_reasons: list[str] = PydanticField(default_factory=list, description="Why alternatives were rejected")
    selected_skills: list[str] = PydanticField(default_factory=list, description="Names of skills used")


# ===========================================================================
# Action instructions
# ===========================================================================

def action_instruction(action_type: ActionType) -> str:
    instructions = {
        ActionType.SHERIFF_RUN: '警长竞选报名：想竞选输出 {"choice":"run"}，否则 {"choice":"pass"}。',
        ActionType.SHERIFF_SPEAK: "警上发言：在 text 中说明你为什么竞选或你的判断。",
        ActionType.SHERIFF_WITHDRAW: '退水选择：继续竞选输出 {"choice":"stay"}，退水输出 {"choice":"withdraw"}。',
        ActionType.SHERIFF_VOTE: "警长投票：target 选择你支持的警长候选人，也可以为 null。",
        ActionType.SHERIFF_BADGE: '警徽处理：移交输出 {"choice":"transfer","target":座位号}，撕毁输出 {"choice":"destroy"}。',
        ActionType.SPEECH_ORDER: '白天发言顺序：顺序发言输出 {"choice":"forward"}，逆序发言输出 {"choice":"reverse"}。',
        ActionType.GUARD_PROTECT: "守卫守护：target 选择一个 candidates 中的玩家。",
        ActionType.WEREWOLF_KILL: "狼人夜刀：target 选择一个 candidates 中的非狼人玩家，不允许空刀。",
        ActionType.SEER_CHECK: "预言家查验：target 选择一个 candidates 中的玩家。",
        ActionType.WITCH_ACT: '女巫用药：可输出 {"choice":"save"}、{"choice":"poison","target":座位号} 或 {"choice":"none"}。',
        ActionType.LAST_WORD: "遗言：在 text 中留下你的判断。",
        ActionType.SPEAK: "白天发言：在 text 中陈述你的判断、怀疑对象或站边。",
        ActionType.WHITE_WOLF_EXPLODE: '白狼王自爆：自爆带人则给 target；不自爆输出 {"choice":"pass"}。',
        ActionType.EXILE_VOTE: "放逐投票：target 选择 candidates 中你最想放逐的人，也可以为 null。",
        ActionType.PK_SPEAK: "PK 发言：在 text 中表达你为什么不该被出。",
        ActionType.PK_VOTE: "PK 投票：target 选择 candidates 中你要投出的玩家，也可以为 null。",
        ActionType.HUNTER_SHOOT: "猎人开枪：target 选择 candidates 中你要带走的玩家。",
    }
    return instructions[action_type]


# ===========================================================================
# LangChain ChatPromptTemplate
# ===========================================================================

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

_SYSTEM_TEMPLATE = """你正在扮演一名狼人杀玩家。你只能根据自己可见的信息行动，不能假设上帝视角。
你是 {player_id} 号玩家，身份: {role}。
请有基本判断：好人应找狼、狼人应隐藏身份并推动好人出局、神职应合理使用技能。
如果竞选警长对你的身份有帮助，可以主动竞选；如果局势不明，可以保守发言。
必须区分 private_reasoning 和 public_text：内部判断不能直接泄露到公开发言。
不要在公开发言中泄露你不可公开解释的私有视角，例如狼人队友、上帝视角或系统真实身份。"""

_USER_TEMPLATE = """当前阶段: {phase}
当前天数: {day}
本次行动: {action_type}
可选目标 candidates: {candidates}
存活玩家: {alive_players}
死亡玩家: {dead_players}
当前警长: {sheriff_id}
你知道的身份: {known_roles}
预言家查验结果: {seer_checks}
行动补充信息: {metadata}
{skill_context}
{hints_block}
{action_instruction}

# 输出格式要求
- 必须只输出 JSON。JSON 字段：
```json
{{
  "schema_version": "1.0",
  "choice": string | null,
  "target": number | null,
  "public_text": string,
  "private_reasoning": string,
  "confidence": 0.0~1.0,
  "alternatives": [number],
  "rejected_reasons": [string],
  "selected_skills": [string]
}}
```
- `public_text` 是公开发言内容。
- `private_reasoning` 是私有推理，不能出现在公开发言中。
- `target` 必须来自 candidates，除非该行动允许弃权或不需要目标。
- `choice` 必须和当前动作匹配。
- `confidence` 是置信度（0.0 到 1.0）。"""


EXPECTED_LLM_SCHEMA_VERSION = "1.0"
SCHEMA_VERSIONED_STAGES = frozenset({"decision", "consolidate", "apply", "evidence", "decision_judge"})


@dataclass(frozen=True)
class PromptBudget:
    """Character budget for model prompts."""

    max_total_chars: int = PROMPT_DEFAULT_MAX_TOTAL_CHARS
    max_message_chars: int = PROMPT_DEFAULT_MAX_MESSAGE_CHARS
    min_message_chars: int = 400


DEFAULT_PROMPT_BUDGET = PromptBudget()


def build_decision_prompt_template() -> ChatPromptTemplate:
    """Return the reusable decision-making ChatPromptTemplate."""
    return ChatPromptTemplate.from_messages([
        ("system", _SYSTEM_TEMPLATE),
        MessagesPlaceholder(variable_name="memory"),
        ("human", _USER_TEMPLATE),
    ])


def schema_version_instruction(stage: str, *, schema_version: str = EXPECTED_LLM_SCHEMA_VERSION) -> str:
    """Return the stage-specific schema-version instruction."""
    if stage not in SCHEMA_VERSIONED_STAGES:
        return ""
    return (
        f"输出 JSON 必须包含字段 `schema_version`，值固定为 \"{schema_version}\"。"
        "除非调用方另有明确 schema，其他字段保持原任务要求。"
    )


def prepare_llm_messages(
    messages: Any,
    *,
    stage: str,
    budget: PromptBudget | None = None,
    schema_version: str = EXPECTED_LLM_SCHEMA_VERSION,
) -> Any:
    """Add shared schema instructions and enforce a prompt character budget."""
    normalized = _normalize_messages(messages)
    instruction = schema_version_instruction(stage, schema_version=schema_version)
    if instruction and not _contains_schema_instruction(normalized):
        normalized.append(SystemMessage(content=instruction))
    return apply_prompt_budget(normalized, budget or DEFAULT_PROMPT_BUDGET)


def apply_prompt_budget(messages: list[Any], budget: PromptBudget) -> list[Any]:
    """Trim message content to fit per-message and total character budgets."""
    max_message = max(0, int(budget.max_message_chars or 0))
    max_total = max(0, int(budget.max_total_chars or 0))
    trimmed = [_replace_message_content(message, _truncate_middle(_message_content(message), max_message))
               for message in messages]
    total = sum(len(_message_content(message)) for message in trimmed)
    if max_total <= 0 or total <= max_total:
        return trimmed

    excess = total - max_total
    min_keep = max(0, int(budget.min_message_chars or 0))
    for index, message in enumerate(trimmed):
        content = _message_content(message)
        if not content:
            continue
        floor = min(min_keep, len(content))
        removable = max(0, len(content) - floor)
        if removable <= 0:
            continue
        remove = min(removable, excess)
        trimmed[index] = _replace_message_content(message, _truncate_middle(content, len(content) - remove))
        excess -= remove
        if excess <= 0:
            break

    if excess > 0:
        for index, message in enumerate(trimmed):
            content = _message_content(message)
            if not content:
                continue
            remove = min(len(content), excess)
            trimmed[index] = _replace_message_content(message, _truncate_middle(content, len(content) - remove))
            excess -= remove
            if excess <= 0:
                break
    return trimmed


def _normalize_messages(messages: Any) -> list[Any]:
    if hasattr(messages, "to_messages"):
        return list(messages.to_messages())
    if isinstance(messages, list):
        return list(messages)
    if isinstance(messages, tuple):
        return list(messages)
    if isinstance(messages, str):
        return [HumanMessage(content=messages)]
    return [HumanMessage(content=str(messages))]


def _contains_schema_instruction(messages: list[Any]) -> bool:
    return any("schema_version" in _message_content(message) for message in messages)


def _message_content(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("content", ""))
    if isinstance(message, tuple) and len(message) >= 2:
        return str(message[1])
    return str(getattr(message, "content", message))


def _replace_message_content(message: Any, content: str) -> Any:
    if isinstance(message, dict):
        updated = dict(message)
        updated["content"] = content
        return updated
    if isinstance(message, tuple) and len(message) >= 2:
        return (message[0], content, *message[2:])
    if isinstance(message, SystemMessage):
        return SystemMessage(content=content)
    if isinstance(message, HumanMessage):
        return HumanMessage(content=content)
    if isinstance(message, AIMessage):
        return AIMessage(content=content)
    if isinstance(message, BaseMessage):
        if hasattr(message, "model_copy"):
            return message.model_copy(update={"content": content})
        if hasattr(message, "copy"):
            return message.copy(update={"content": content})
    return HumanMessage(content=content)


def _truncate_middle(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    marker = f"\n...[prompt truncated {len(text) - limit} chars]...\n"
    if limit <= len(marker):
        return marker[:limit]
    head = (limit - len(marker)) // 2
    tail = limit - len(marker) - head
    return text[:head] + marker + text[-tail:]


# ===========================================================================
# Memory message formatter
# ===========================================================================

def format_memory_messages(memory_context: dict) -> list:
    """Format segment-based memory into LangChain messages.

    Returns a list of SystemMessage (for compressed summaries)
    and HumanMessage (for recent closed + open segments).
    """
    messages = []

    compressed = memory_context.get("compressed_segment_summaries") or []
    if compressed:
        lines = []
        for cs in compressed:
            seg_key = cs.get("segment_key", "?")
            summary = cs.get("summary", "")
            lines.append(f"[{seg_key}] {summary}")
            for evt in cs.get("key_events", []):
                lines.append(f"  - {evt}")
            for player, note in cs.get("player_notes", {}).items():
                lines.append(f"  - P{player}: {note}")
            for unk in cs.get("unknowns", []):
                lines.append(f"  - 未知: {unk}")
        messages.append(SystemMessage(content="更早阶段摘要:\n" + "\n".join(f"- {l}" for l in lines)))

    recent_closed = memory_context.get("recent_closed_segments") or []
    for seg in recent_closed:
        seg_key = seg.get("segment_key", "?")
        events = seg.get("events") or []
        if events:
            text = "\n".join(f"- {e.get('text', e.get('content', str(e)))}" for e in events)
            messages.append(HumanMessage(content=f"{seg_key} 完整事件:\n{text}"))

    open_events = memory_context.get("open_segment") or []
    open_key = memory_context.get("open_segment_key")
    if open_events:
        text = "\n".join(f"- {e.get('text', e.get('content', str(e)))}" for e in open_events)
        label = f"{open_key} 当前阶段" if open_key else "当前阶段"
        messages.append(HumanMessage(content=f"{label}:\n{text}"))

    return messages


# ===========================================================================
# Part 5: Markdown Skill loader + router (unchanged)
# ===========================================================================

@dataclass(slots=True)
class MarkdownSkill:
    name: str
    relative_path: str = ""
    description: str = ""
    role: Role | None = None
    applicable_actions: set[ActionType] = field(default_factory=set)
    requires: dict[str, Any] = field(default_factory=dict)
    body: str = ""
    evolution: dict[str, Any] = field(default_factory=lambda: {"enabled": False, "allowed_actions": []})
    status: str = "active"
    runtime_body: str = ""


@dataclass(frozen=True, slots=True)
class SkillLoadDiagnostic:
    path: str
    message: str
    severity: str = "warning"

    def format(self) -> str:
        return f"{self.severity}: {self.path}: {self.message}"


@dataclass(slots=True)
class SkillLoadReport:
    skills: list[MarkdownSkill] = field(default_factory=list)
    diagnostics: list[SkillLoadDiagnostic] = field(default_factory=list)
    signature: tuple[tuple[str, int, int], ...] = field(default_factory=tuple)

    def copy(self) -> "SkillLoadReport":
        return SkillLoadReport(
            skills=list(self.skills),
            diagnostics=list(self.diagnostics),
            signature=self.signature,
        )


_RUNTIME_SECTIONS = {"Strategy", "Heuristics", "Decision Rules", "Risk Boundaries"}
_SYSTEM_SECTIONS = {"Examples", "Deprecated Rules", "Changelog", "Provenance", "Evaluation Notes"}
_FORBIDDEN_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bP\d+\b", re.IGNORECASE), "player number (P1/P2/…)"),
    (re.compile(r"\d+号"), "player number (N号)"),
    (re.compile(r"\bgame_id\b", re.IGNORECASE), "game_id"),
    (re.compile(r"\brun_id\b", re.IGNORECASE), "run_id"),
    (re.compile(r"\bseed\b", re.IGNORECASE), "seed"),
    (re.compile(r"\bgpt[-\s]?[34o]", re.IGNORECASE), "model name (GPT)"),
    (re.compile(r"\bclaude[-\s]?", re.IGNORECASE), "model name (Claude)"),
    (re.compile(r"\bwin[-_]?rate\b", re.IGNORECASE), "A/B result (win_rate)"),
]
_RUNTIME_BODY_SOFT_LIMIT = 1800
_RUNTIME_BODY_HARD_LIMIT = 2400
_SKILL_FILE_TOTAL_SOFT_LIMIT = 6000
_ACTION_ALIASES: dict[str, tuple[ActionType, ...]] = {
    "vote": (ActionType.SHERIFF_VOTE, ActionType.EXILE_VOTE, ActionType.PK_VOTE),
}


def validate_runtime_body(body: str) -> list[str]:
    violations: list[str] = []
    for pattern, label in _FORBIDDEN_PATTERNS:
        if pattern.search(body):
            violations.append(label)
    return violations


def check_skill_limits(skill: MarkdownSkill) -> list[str]:
    issues: list[str] = []
    rb_len = len(skill.runtime_body)
    if rb_len > _RUNTIME_BODY_HARD_LIMIT:
        issues.append(f"[hard] runtime_body length {rb_len} exceeds hard limit {_RUNTIME_BODY_HARD_LIMIT}")
    elif rb_len > _RUNTIME_BODY_SOFT_LIMIT:
        issues.append(f"[soft] runtime_body length {rb_len} exceeds soft limit {_RUNTIME_BODY_SOFT_LIMIT}")
    total_len = len(skill.body)
    if total_len > _SKILL_FILE_TOTAL_SOFT_LIMIT:
        issues.append(f"[soft] skill body length {total_len} exceeds soft limit {_SKILL_FILE_TOTAL_SOFT_LIMIT}")
    return issues


_FRONT_MATTER_SEP = "---"


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    """Parse YAML-like front matter from a Markdown string. Delegates to util/text.py."""
    return parse_yaml_front_matter(text)


def _normalize_evolution(value: Any) -> dict[str, Any]:
    evolution = dict(value) if isinstance(value, dict) else {}
    raw_allowed = evolution.get("allowed_actions", [])
    if isinstance(raw_allowed, str): allowed_actions = [raw_allowed]
    elif isinstance(raw_allowed, list): allowed_actions = [str(a) for a in raw_allowed]
    else: allowed_actions = []
    evolution["enabled"] = bool(evolution.get("enabled", False))
    evolution["allowed_actions"] = allowed_actions
    return evolution


def _extract_runtime_sections(body: str) -> str:
    heading_pattern = re.compile(r"^##\s+(.+)$", re.MULTILINE)
    headings = heading_pattern.findall(body)
    if not headings:
        return body
    has_runtime = any(h.strip() in _RUNTIME_SECTIONS for h in headings)
    if not has_runtime:
        return body
    sections = split_markdown_sections(body)
    runtime_parts = []
    for heading, content in sections:
        if heading.strip() in _RUNTIME_SECTIONS:
            runtime_parts.append(f"## {heading}\n{content}")
    return "\n\n".join(runtime_parts).strip()


def _relative_skill_path(path: Path, root: Path | None) -> str:
    try:
        if root is not None:
            return path.relative_to(root).as_posix()
    except ValueError:
        pass
    return path.name


def _add_skill_diagnostic(
    diagnostics: list[SkillLoadDiagnostic] | None,
    path: Path,
    root: Path | None,
    message: str,
    *,
    severity: str = "warning",
) -> None:
    if diagnostics is None:
        return
    diagnostics.append(SkillLoadDiagnostic(
        path=_relative_skill_path(path, root),
        message=message,
        severity=severity,
    ))


def _load_skill_file(
    path: Path,
    *,
    root: Path | None = None,
    diagnostics: list[SkillLoadDiagnostic] | None = None,
) -> MarkdownSkill | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        _add_skill_diagnostic(diagnostics, path, root, f"failed to read file: {exc}", severity="error")
        return None
    front, body = parse_front_matter(text)
    if not front:
        _add_skill_diagnostic(diagnostics, path, root, "missing YAML front matter", severity="error")
        return None
    raw_name = front.get("name", path.stem)
    name = str(raw_name).strip() if raw_name is not None else ""
    if not name:
        _add_skill_diagnostic(diagnostics, path, root, f"empty name, using '{path.stem}'")
        name = path.stem
    description = front.get("description", "")
    role: Role | None = None
    role_name = front.get("role")
    if role_name:
        try:
            role = Role(role_name)
        except (ValueError, KeyError):
            _add_skill_diagnostic(diagnostics, path, root, f"unknown role '{role_name}' ignored")
    raw_actions = front.get("applicable_actions", [])
    if isinstance(raw_actions, str):
        raw_actions = [raw_actions]
    elif not isinstance(raw_actions, list):
        _add_skill_diagnostic(diagnostics, path, root, "applicable_actions must be a string or list")
        raw_actions = []
    actions: set[ActionType] = set()
    for a in raw_actions:
        action_name = a.value if isinstance(a, ActionType) else str(a).strip()
        if action_name in _ACTION_ALIASES:
            actions.update(_ACTION_ALIASES[action_name])
            continue
        try:
            actions.add(ActionType(action_name))
        except (ValueError, KeyError):
            _add_skill_diagnostic(diagnostics, path, root, f"unknown action '{action_name}' ignored")
    requires = front.get("requires", {})
    if not isinstance(requires, dict):
        _add_skill_diagnostic(diagnostics, path, root, "requires must be a mapping; ignored")
        requires = {}
    evolution = _normalize_evolution(front.get("evolution", {}))
    status = str(front.get("status", "active")).strip().lower()
    if status not in ("active", "deprecated"):
        _add_skill_diagnostic(diagnostics, path, root, f"unknown status '{status}', using 'active'")
        status = "active"
    full_body = body.strip()
    runtime_body = _extract_runtime_sections(full_body)
    skill = MarkdownSkill(name=name, relative_path=_relative_skill_path(path, root), description=description,
        role=role, applicable_actions=actions, requires=requires, body=full_body,
        evolution=evolution, status=status, runtime_body=runtime_body)
    violations = validate_runtime_body(runtime_body)
    if violations:
        _log.warning("Skill %s has forbidden runtime content: %s", name, violations)
        _add_skill_diagnostic(
            diagnostics,
            path,
            root,
            f"forbidden runtime content: {', '.join(violations)}",
        )
    limit_issues = check_skill_limits(skill)
    for issue in limit_issues:
        _log.warning("Skill %s limit issue: %s", name, issue)
        _add_skill_diagnostic(diagnostics, path, root, f"limit issue: {issue}")
    return skill


_SkillSignature = tuple[tuple[str, int, int], ...]
_skill_cache: dict[Path, tuple[_SkillSignature, SkillLoadReport]] = {}


def _scan_skill_files(root: Path) -> tuple[list[Path], _SkillSignature, list[SkillLoadDiagnostic]]:
    diagnostics: list[SkillLoadDiagnostic] = []
    if not root.is_dir():
        return [], (), diagnostics
    try:
        files = sorted(path for path in root.rglob("*.md") if path.is_file())
    except OSError as exc:
        diagnostics.append(SkillLoadDiagnostic(path=".", message=f"failed to scan skill directory: {exc}", severity="error"))
        return [], (), diagnostics

    signature_entries: list[tuple[str, int, int]] = []
    for path in files:
        rel_path = _relative_skill_path(path, root)
        try:
            stat = path.stat()
            signature_entries.append((rel_path, stat.st_mtime_ns, stat.st_size))
        except OSError as exc:
            diagnostics.append(SkillLoadDiagnostic(
                path=rel_path,
                message=f"failed to stat file: {exc}",
                severity="error",
            ))
            signature_entries.append((rel_path, -1, -1))
    return files, tuple(signature_entries), diagnostics


def load_markdown_skill_report(root: Path) -> SkillLoadReport:
    root = Path(root).resolve()
    files, signature, diagnostics = _scan_skill_files(root)
    cached = _skill_cache.get(root)
    if cached is not None and cached[0] == signature:
        return cached[1].copy()

    skills: list[MarkdownSkill] = []
    for md_path in files:
        skill = _load_skill_file(md_path, root=root, diagnostics=diagnostics)
        if skill is not None:
            skills.append(skill)
    report = SkillLoadReport(skills=skills, diagnostics=diagnostics, signature=signature)
    _skill_cache[root] = (signature, report.copy())
    return report


def load_markdown_skill_diagnostics(root: Path) -> list[SkillLoadDiagnostic]:
    return load_markdown_skill_report(root).diagnostics


def load_markdown_skills(root: Path) -> list[MarkdownSkill]:
    return load_markdown_skill_report(root).skills


@dataclass
class SkillIndex:
    by_role: dict[Role, list[MarkdownSkill]]


_SKILL_CACHE_MAP: dict[Path, tuple[_SkillSignature, SkillIndex]] = {}
_CURRENT_SKILL_ROOT: Path | None = None


def configure_skill_root(root: Path | str | None = None) -> None:
    global _CURRENT_SKILL_ROOT
    _CURRENT_SKILL_ROOT = Path(root) if root is not None else None
    _skill_cache.clear()
    _SKILL_CACHE_MAP.clear()


def _load_skill_index(all_skills: list[MarkdownSkill]) -> SkillIndex:
    by_role: dict[Role, list[MarkdownSkill]] = {}
    for skill in all_skills:
        if skill.role is not None: by_role.setdefault(skill.role, []).append(skill)
    return SkillIndex(by_role=by_role)


def _get_skill_index(skill_root: Path | None = None) -> SkillIndex:
    root = skill_root or _CURRENT_SKILL_ROOT
    if root is None: return SkillIndex(by_role={})
    root = root.resolve()
    report = load_markdown_skill_report(root)
    cached = _SKILL_CACHE_MAP.get(root)
    if cached is not None and cached[0] == report.signature:
        return cached[1]
    index = _load_skill_index(report.skills)
    _SKILL_CACHE_MAP[root] = (report.signature, index)
    return index


def _requirements_match(requires: dict[str, Any], ctx: Any) -> bool:
    if not ctx.request.metadata: return not requires
    for key, expected in requires.items():
        if ctx.request.metadata.get(key) != expected: return False
    return True


def select_skills(ctx: Any, role: Role, *, skill_root: Path | None = None) -> list[MarkdownSkill]:
    idx = _get_skill_index(skill_root)
    selected: list[MarkdownSkill] = []
    action_type = ctx.request.action_type
    for skill in idx.by_role.get(role, []):
        if skill.status != "active": continue
        if not skill.applicable_actions or action_type in skill.applicable_actions:
            if _requirements_match(skill.requires, ctx): selected.append(skill)
    selected.sort(key=lambda s: (0 if action_type in s.applicable_actions else 1, s.name))
    return selected[:3]


def format_skill_context(selected: list[MarkdownSkill], action_type: ActionType) -> str:
    parts: list[str] = []
    if selected:
        parts.append("## role strategy Skill"); parts.append("")
        action_skills = [s for s in selected if action_type in s.applicable_actions]
        other_skills = [s for s in selected if action_type not in s.applicable_actions]
        for skill in action_skills + other_skills:
            body = skill.runtime_body or skill.body
            parts.append(f"### {skill.name}"); parts.append(""); parts.append(body); parts.append("")
    return chr(10).join(parts).strip()
