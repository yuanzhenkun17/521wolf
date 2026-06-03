"""Skill applier — applies consolidation proposals to skill files via LLM.

Takes a ``SkillConsolidation`` (batch of proposals) and the current skill
files, asks the LLM to produce modified files, validates the result through
13 safety checks, smoke-tests via ``load_markdown_skills``, and returns
the new skill contents along with diffs.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from engine.models import ActionType, Role
from agent.learning.evolution.models import (
    SkillConsolidation,
    SkillDiff,
    SkillProposal,
)
from agent.learning.evolution.store import normalize_skill_path, normalize_skill_text
from agent.infrastructure.llm import ModelAdapter
from agent.knowledge.skills.loader import load_markdown_skills, parse_front_matter

_log = logging.getLogger(__name__)

# Constants
CONFIDENCE_THRESHOLD = 0.5
MAX_SKILL_LENGTH = 5000  # chars per file
MAX_CHANGED_FILES = 5
MAX_ACTIVE_SKILLS_PER_ROLE = 6
CREATE_SKILL_ACTION = "create_skill"

# Global whitelist — code defines what action types exist.
# Skills declare which subset they allow via evolution.allowed_actions.
GLOBAL_ALLOWED_PROPOSAL_ACTIONS = {
    "append_rule",
    "rewrite_section",
    "deprecate_rule",
    CREATE_SKILL_ACTION,
}
GLOBAL_ALLOWED_MODIFY_ACTIONS = GLOBAL_ALLOWED_PROPOSAL_ACTIONS - {CREATE_SKILL_ACTION}
VALID_GAME_ACTIONS = {a.value for a in ActionType}
VALID_ROLES = {r.value for r in Role}
CREATE_SKILL_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,48}$")

# Public API
async def apply_proposals(
    current_skills: dict[str, str],
    proposals: SkillConsolidation,
    model_adapter: ModelAdapter,
) -> tuple[dict[str, str], list[SkillDiff]]:
    """Apply eligible proposals to skill files via LLM.

    Parameters
    ----------
    current_skills:
        Mapping of ``{filename: content}`` for existing skill files.
    proposals:
        The consolidation batch produced by the LLM consolidator.
    model_adapter:
        An LLM adapter implementing the ``ModelAdapter`` protocol.

    Returns
    -------
    tuple[dict[str, str], list[SkillDiff]]
        ``(new_skills, diffs)`` where *new_skills* is the updated mapping
        and *diffs* describes every change that was applied.  On any
        unrecoverable error the function returns the original skills with
        an empty diff list (graceful degradation).
    """
    # Step 1: Filter eligible proposals
    eligible = _filter_eligible(proposals.proposals)
    if not eligible:
        _log.info("No eligible proposals after filtering")
        return dict(current_skills), []

    # Step 2: Conflict detection
    eligible = _resolve_conflicts(eligible)

    # Deduplicate: after conflict resolution some proposals were skipped
    active = [p for p in eligible if p.status == "proposed"]
    if not active:
        _log.info("All proposals skipped after conflict resolution")
        return dict(current_skills), []

    # Cap at MAX_CHANGED_FILES
    if len(active) > MAX_CHANGED_FILES:
        _log.warning(
            "Too many active proposals (%d), keeping first %d",
            len(active),
            MAX_CHANGED_FILES,
        )
        active = active[:MAX_CHANGED_FILES]

    # Step 3: Build LLM prompt and call
    try:
        llm_response = await _call_llm(current_skills, active, proposals.role, model_adapter)
    except Exception:
        _log.exception("LLM call failed during proposal application")
        return dict(current_skills), []

    # Step 4: Parse LLM output
    try:
        parsed = _parse_llm_output(llm_response)
    except ValueError as exc:
        _log.error("Failed to parse LLM output: %s", exc)
        return dict(current_skills), []

    proposed_files: dict[str, str] = parsed.get("files", {})
    changes: list[dict[str, str]] = parsed.get("changes", [])

    # Step 5: Validate (13 checks — any failure rejects all)
    errors = _validate_all(current_skills, proposed_files, active, proposals.role)
    if errors:
        for err in errors:
            _log.error("Validation failed: %s", err)
        return dict(current_skills), []

    # Step 6: Smoke test — write to temp dir, verify skills load
    smoke_ok, smoke_err = _smoke_test(proposed_files)
    if not smoke_ok:
        _log.error("Smoke test failed: %s", smoke_err)
        return dict(current_skills), []

    # Step 7: Build diffs
    diffs = _build_diffs(current_skills, proposed_files, changes, active)

    # Step 8: Return
    _log.info(
        "Applied %d proposals, modified %d files",
        len(active),
        len(proposed_files),
    )
    return proposed_files, diffs


# Filtering & conflict resolution
def _filter_eligible(proposals: list[SkillProposal]) -> list[SkillProposal]:
    """Keep proposals with confidence >= threshold, risk != high, status == proposed."""
    eligible: list[SkillProposal] = []
    for p in proposals:
        if p.status != "proposed":
            continue
        if p.confidence < CONFIDENCE_THRESHOLD:
            _log.debug("Skipping %s: confidence %.2f < threshold", p.proposal_id, p.confidence)
            continue
        if p.risk == "high":
            _log.debug("Skipping %s: risk is high", p.proposal_id)
            continue
        eligible.append(p)
    return eligible


def _resolve_conflicts(proposals: list[SkillProposal]) -> list[SkillProposal]:
    """If proposal A conflicts_with B, skip both. Returns a new list, does not mutate input."""
    by_id = {p.proposal_id: p for p in proposals}
    skip_ids: set[str] = set()

    for p in proposals:
        for conflict_id in p.conflicts_with:
            if conflict_id in by_id:
                skip_ids.add(p.proposal_id)
                skip_ids.add(conflict_id)

    result = []
    for p in proposals:
        if p.proposal_id in skip_ids:
            import copy
            skipped = copy.deepcopy(p)
            skipped.status = "skipped"
            _log.debug("Skipping %s due to conflict", p.proposal_id)
            result.append(skipped)
        else:
            result.append(p)
    return result


# LLM interaction
def _build_llm_prompt(
    current_skills: dict[str, str],
    eligible: list[SkillProposal],
    role: str,
) -> str:
    """Build the prompt that asks the LLM to produce modified skill files."""
    parts: list[str] = []
    parts.append(
        "You are a skill-file editor for a Werewolf game AI agent. "
        "Apply the atomic rule proposals below to the current skill files. "
        "Each proposal is a candidate rule card backed by recent games; do not invent unrelated rules. "
        "Return ONLY a JSON object with the exact shape:\n"
        '{"files": {"filename.md": "full file content", ...}, '
        '"changes": [{"filename": "file.md", "action": "modified|created", '
        '"description": "brief summary"}]}\n'
    )
    parts.append(f"\nRole: {role}\n")
    parts.append(
        "Rules:\n"
        f"- Existing files may only be modified when targeted by an eligible proposal.\n"
        f"- New files may only be created by action_type={CREATE_SKILL_ACTION}.\n"
        f"- A created skill target must be exactly '<slug>.md' inside the Role={role} version.\n"
        "- Return every existing file in files, unchanged unless it is targeted.\n"
        "- Do not change front-matter role/name/applicable_actions/evolution for existing files.\n"
        "- For created files, front matter must include role, name, applicable_actions, "
        "and evolution.enabled=true with modification allowed_actions.\n"
        "- SLOW UPDATE PROTECTION: If a file contains `<!-- slow_update -->...<!-- /slow_update -->` "
        "regions, you MUST preserve their content exactly. You may APPEND new content inside the region, "
        "but you must NOT delete or modify existing content within these markers.\n"
    )

    parts.append("## Current skill files\n")
    if current_skills:
        for fname, content in current_skills.items():
            parts.append(f"### {fname}\n```\n{content}\n```\n")
    else:
        parts.append("(empty baseline: no current skill files)\n")

    parts.append("## Proposals to apply\n")
    for p in eligible:
        parts.append(
            f"- **{p.proposal_id}** (action={p.action_type}, target={p.target_file}, "
            f"confidence={p.confidence:.2f})\n"
            f"  rationale: {p.rationale}\n"
            f"  content: {p.content}\n"
        )
        if p.section:
            parts.append(f"  section: {p.section}\n")

    parts.append(
        "\nReturn the JSON object now. Do NOT add commentary outside the JSON."
    )
    return "\n".join(parts)


async def _call_llm(
    current_skills: dict[str, str],
    eligible: list[SkillProposal],
    role: str,
    model_adapter: ModelAdapter,
) -> str:
    """Call the LLM with the application prompt."""
    prompt = _build_llm_prompt(current_skills, eligible, role)
    messages = [{"role": "user", "content": prompt}]
    return await model_adapter.complete(messages)


def _parse_llm_output(raw: str) -> dict[str, Any]:
    """Parse the LLM JSON response. Raises ValueError on bad JSON."""
    # Strip markdown code fences if present
    text = raw.strip()
    if text.startswith("```"):
        # Remove opening fence (possibly with language tag)
        first_nl = text.index("\n")
        text = text[first_nl + 1 :]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("LLM output is not a JSON object")
    if "files" not in data:
        raise ValueError("LLM output missing 'files' key")
    return data


# Validation (13 checks)
def _validate_all(
    current_skills: dict[str, str],
    proposed_files: dict[str, str],
    eligible: list[SkillProposal],
    role: str,
) -> list[str]:
    """Run all 13 validation checks. Returns list of error strings (empty = pass)."""
    errors: list[str] = []
    eligible_targets = {p.target_file for p in eligible}
    create_targets = {
        p.target_file for p in eligible
        if p.action_type == CREATE_SKILL_ACTION
    }

    # 1. Only modify/create files targeted by eligible proposals.
    # Unchanged current files may be included in the full output.
    for fname, new_content in proposed_files.items():
        err = _validate_path_safe(fname)
        if err:
            errors.append(err)
        old_content = current_skills.get(fname)
        if fname in eligible_targets:
            continue
        if old_content is None:
            errors.append(f"File '{fname}' was created without an eligible proposal")
        elif not _same_skill_text(old_content, new_content):
            errors.append(f"File '{fname}' was modified without an eligible proposal")

    # 1b. Check proposal action_type against global whitelist and per-skill allowed_actions
    for p in eligible:
        err = _validate_path_safe(p.target_file)
        if err:
            errors.append(f"[{p.target_file}] {err}")
        if p.action_type not in GLOBAL_ALLOWED_PROPOSAL_ACTIONS:
            errors.append(f"[{p.target_file}] action_type '{p.action_type}' not in global whitelist")

        if p.action_type == CREATE_SKILL_ACTION:
            if p.target_file in current_skills:
                errors.append(f"[{p.target_file}] create_skill target already exists")
            if p.target_file not in proposed_files:
                errors.append(f"[{p.target_file}] create_skill target missing from LLM output")
            err = _validate_create_skill_target(p.target_file, role)
            if err:
                errors.append(f"[{p.target_file}] {err}")
            continue

        if p.target_file not in current_skills:
            errors.append(
                f"[{p.target_file}] target file does not exist; use {CREATE_SKILL_ACTION}"
            )
            continue

        # Per-skill check: load old content to get evolution.allowed_actions
        old_content = current_skills.get(p.target_file, "")
        if old_content:
            old_fm, _ = parse_front_matter(old_content)
            evo = old_fm.get("evolution", {})
            if isinstance(evo, dict) and evo.get("enabled"):
                allowed = set(evo.get("allowed_actions", []))
                if allowed and p.action_type not in allowed:
                    errors.append(
                        f"[{p.target_file}] action_type '{p.action_type}' "
                        f"not in skill's evolution.allowed_actions {allowed}"
                    )

    # 2. No file deletion — all current files must be present
    for fname in current_skills:
        if fname not in proposed_files:
            errors.append(f"File '{fname}' would be deleted (not in output)")

    # Per-file checks
    for fname, new_content in proposed_files.items():
        old_content = current_skills.get(fname)
        is_new_file = old_content is None

        if is_new_file:
            if fname not in create_targets:
                errors.append(f"[{fname}] new file requires action_type '{CREATE_SKILL_ACTION}'")
            err = _validate_create_skill_file(fname, new_content, role)
            if err:
                errors.append(f"[{fname}] {err}")
        else:
            # 3. name field unchanged
            err = _validate_name_unchanged(new_content, old_content)
            if err:
                errors.append(f"[{fname}] {err}")

            # 4. applicable_actions not expanded
            err = _validate_applicable_actions_not_expanded(new_content, old_content)
            if err:
                errors.append(f"[{fname}] {err}")

            # 5. role unchanged
            err = _validate_role_unchanged(new_content, old_content)
            if err:
                errors.append(f"[{fname}] {err}")

            # 6. evolution.enabled not changed from false to true without proposal
            err = _validate_evolvable_not_flipped(new_content, old_content, eligible, fname)
            if err:
                errors.append(f"[{fname}] {err}")

            # 7. evolution field must not be modified by applier
            err = _validate_evolution_unchanged(new_content, old_content)
            if err:
                errors.append(f"[{fname}] {err}")

        # 8. Path safety
        err = _validate_path_safe(fname)
        if err:
            errors.append(err)

        # 9. YAML front matter parseable
        fm = _validate_front_matter(new_content)
        if fm is None:
            errors.append(f"[{fname}] YAML front matter is not parseable")

        # 10. File length limit
        if len(new_content) > MAX_SKILL_LENGTH:
            errors.append(
                f"[{fname}] File length {len(new_content)} exceeds limit {MAX_SKILL_LENGTH}"
            )

        # 11. No other role's private strategy leakage
        err = _validate_no_foreign_strategy_leakage(new_content, eligible)
        if err:
            errors.append(f"[{fname}] {err}")

        # 13. Slow update region preservation
        if not is_new_file:
            err = _validate_slow_update_preserved(old_content, new_content)
            if err:
                errors.append(f"[{fname}] {err}")

    # 11b. Active skill cap for the role being evolved.
    role_skill_count = _count_role_skill_files(proposed_files, role)
    if role_skill_count > MAX_ACTIVE_SKILLS_PER_ROLE:
        errors.append(
            f"Role '{role}' would have {role_skill_count} active skills; "
            f"limit is {MAX_ACTIVE_SKILLS_PER_ROLE}"
        )

    # 12. Diff size limit — total changed content bounded by MAX_CHANGED_FILES * MAX_SKILL_LENGTH
    total_new = sum(len(v) for v in proposed_files.values())
    if total_new > MAX_CHANGED_FILES * MAX_SKILL_LENGTH:
        errors.append(
            f"Total output size {total_new} exceeds limit "
            f"{MAX_CHANGED_FILES * MAX_SKILL_LENGTH}"
        )

    return errors


import re

_SLOW_UPDATE_PATTERN = re.compile(
    r"<!--\s*slow_update\s*-->(.*?)<!--\s*/slow_update\s*>",
    re.DOTALL,
)


def _validate_slow_update_preserved(old_content: str, new_content: str) -> str | None:
    """Check that slow_update regions in old_content are preserved in new_content.

    The new file may have additional content appended inside the slow_update region,
    but existing content must not be deleted or modified.
    """
    old_regions = _SLOW_UPDATE_PATTERN.findall(old_content)
    if not old_regions:
        return None  # No slow_update regions to protect

    new_regions = _SLOW_UPDATE_PATTERN.findall(new_content)
    if not new_regions:
        return "slow_update region was deleted"

    # Check that each old region's content is a substring of the corresponding new region
    # (allowing for appended content)
    for i, old_region in enumerate(old_regions):
        old_text = old_region.strip()
        if i >= len(new_regions):
            return f"slow_update region {i+1} was deleted"
        new_text = new_regions[i].strip()
        if old_text not in new_text:
            return (
                f"slow_update region {i+1} content was modified "
                f"(old: {len(old_text)} chars, new: {len(new_text)} chars)"
            )

    return None


def _same_skill_text(left: str, right: str) -> bool:
    """Compare skill content using the same normalization as version hashing."""
    return normalize_skill_text(left) == normalize_skill_text(right)


def _as_str_list(value: Any) -> list[str]:
    """Normalize a front-matter scalar/list field into strings."""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []


def _validate_create_skill_target(path: str, role: str) -> str | None:
    """Validate create_skill path shape: exactly '<slug>.md' in the role version."""
    try:
        normalized = normalize_skill_path(path)
    except ValueError as exc:
        return str(exc)
    if normalized != path.replace("\\", "/"):
        return f"target_file must already be normalized, got '{path}'"
    p = PurePosixPath(normalized)
    if len(p.parts) != 1:
        return f"create_skill target_file must be exactly '<slug>.md' inside the '{role}' role version"
    slug = p.stem
    if not CREATE_SKILL_SLUG_RE.match(slug):
        return (
            "create_skill slug must use lowercase letters, digits, '-' or '_' "
            "and be 2-49 chars"
        )
    return None


def _validate_create_skill_file(path: str, content: str, role: str) -> str | None:
    """Validate the full content of a newly created skill file."""
    err = _validate_create_skill_target(path, role)
    if err:
        return err

    fm = _validate_front_matter(content)
    if fm is None:
        return "YAML front matter is not parseable"

    file_role = str(fm.get("role", ""))
    if file_role != role:
        return f"role must be '{role}', got '{file_role}'"
    if file_role not in VALID_ROLES:
        return f"unknown role '{file_role}'"

    name = str(fm.get("name", "")).strip()
    if not name:
        return "name is required"

    game_actions = set(_as_str_list(fm.get("applicable_actions", [])))
    if not game_actions:
        return "applicable_actions must contain at least one game action"
    invalid_game_actions = sorted(game_actions - VALID_GAME_ACTIONS)
    if invalid_game_actions:
        return f"unknown applicable_actions: {invalid_game_actions}"

    evo = fm.get("evolution", {})
    if not isinstance(evo, dict):
        return "evolution must be a mapping"
    if not bool(evo.get("enabled", False)):
        return "created skills must set evolution.enabled=true"
    allowed_modify_actions = set(_as_str_list(evo.get("allowed_actions", [])))
    if not allowed_modify_actions:
        return "created skills must declare evolution.allowed_actions"
    invalid_modify_actions = sorted(allowed_modify_actions - GLOBAL_ALLOWED_MODIFY_ACTIONS)
    if invalid_modify_actions:
        return f"invalid evolution.allowed_actions: {invalid_modify_actions}"
    return None


def _count_role_skill_files(files: dict[str, str], role: str) -> int:
    """Count markdown skill files whose front matter belongs to *role*."""
    count = 0
    for fname, content in files.items():
        if PurePosixPath(fname.replace("\\", "/")).suffix != ".md":
            continue
        try:
            fm, _ = parse_front_matter(content)
        except Exception:
            continue
        if str(fm.get("role", "")) == role:
            count += 1
    return count


def _validate_front_matter(content: str) -> dict | None:
    """Return parsed front matter dict, or None if unparseable."""
    try:
        fm, _ = parse_front_matter(content)
        if not fm:
            return None
        return fm
    except Exception:
        return None


def _validate_role_unchanged(new_content: str, old_content: str) -> str | None:
    """Return error string if the 'role' field changed."""
    new_fm, _ = parse_front_matter(new_content)
    old_fm, _ = parse_front_matter(old_content)
    new_role = new_fm.get("role")
    old_role = old_fm.get("role")
    if old_role and new_role != old_role:
        return f"role changed from '{old_role}' to '{new_role}'"
    return None


def _validate_applicable_actions_not_expanded(
    new_content: str, old_content: str
) -> str | None:
    """Return error string if applicable_actions gained new entries."""
    new_fm, _ = parse_front_matter(new_content)
    old_fm, _ = parse_front_matter(old_content)

    def _to_set(val: Any) -> set[str]:
        if isinstance(val, list):
            return set(str(v) for v in val)
        if isinstance(val, str):
            return {val}
        return set()

    old_actions = _to_set(old_fm.get("applicable_actions", []))
    new_actions = _to_set(new_fm.get("applicable_actions", []))
    if old_actions and not old_actions.issubset(new_actions):
        return "applicable_actions was reduced (existing actions removed)"
    added = new_actions - old_actions
    if added:
        return f"applicable_actions expanded with: {added}"
    return None


def _validate_name_unchanged(new_content: str, old_content: str) -> str | None:
    """Return error string if 'name' field changed."""
    new_fm, _ = parse_front_matter(new_content)
    old_fm, _ = parse_front_matter(old_content)
    if old_fm.get("name") and new_fm.get("name") != old_fm.get("name"):
        return f"name changed from '{old_fm['name']}' to '{new_fm.get('name')}'"
    return None


def _validate_evolution_unchanged(new_content: str, old_content: str) -> str | None:
    """Return error if the evolution field was modified."""
    import json as _json
    new_fm, _ = parse_front_matter(new_content)
    old_fm, _ = parse_front_matter(old_content)
    old_evo = _json.dumps(old_fm.get("evolution", {}), sort_keys=True)
    new_evo = _json.dumps(new_fm.get("evolution", {}), sort_keys=True)
    if old_evo != new_evo:
        return "evolution field must not be modified by applier"
    return None


def _validate_path_safe(path: str) -> str | None:
    """Return error string if path is unsafe."""
    try:
        normalize_skill_path(path)
    except ValueError as exc:
        return f"Path '{path}' is unsafe: {exc}"
    return None


def _validate_evolvable_not_flipped(
    new_content: str,
    old_content: str,
    eligible: list[SkillProposal],
    fname: str,
) -> str | None:
    """Return error if evolution.enabled changed from false to true without a proposal."""
    new_fm, _ = parse_front_matter(new_content)
    old_fm, _ = parse_front_matter(old_content)
    old_evo = old_fm.get("evolution", {})
    new_evo = new_fm.get("evolution", {})
    old_enabled = bool(old_evo.get("enabled", False)) if isinstance(old_evo, dict) else False
    new_enabled = bool(new_evo.get("enabled", False)) if isinstance(new_evo, dict) else False
    if not old_enabled and new_enabled:
        has_proposal = any(p.target_file == fname for p in eligible)
        if not has_proposal:
            return "evolution.enabled changed from false to true without a proposal"
    return None


def _validate_no_foreign_strategy_leakage(
    content: str,
    eligible: list[SkillProposal],
) -> str | None:
    """Check for private strategy belonging to a different role.

    This is a heuristic: if the content mentions a role name that doesn't
    match any proposal's target role, flag it.  We use the consolidation
    role as the expected role.
    """
    # Collect the set of roles referenced by eligible proposals (via target_file path)
    # Skill files are typically at skills/<role>/<file>.md
    known_roles: set[str] = set()
    for p in eligible:
        parts = Path(p.target_file).parts
        if len(parts) >= 2:
            known_roles.add(parts[0])

    fm, body = parse_front_matter(content)
    file_role = fm.get("role", "")
    if file_role and file_role not in known_roles and known_roles:
        return f"role '{file_role}' does not match any eligible proposal role: {known_roles}"
    return None


# Smoke test
def _smoke_test(proposed_files: dict[str, str]) -> tuple[bool, str]:
    """Write files to a temp dir and verify they load via load_markdown_skills."""
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for fname, content in proposed_files.items():
                fpath = root / fname
                fpath.parent.mkdir(parents=True, exist_ok=True)
                fpath.write_text(content, encoding="utf-8")
            skills = load_markdown_skills(root)
            if not skills:
                return False, "load_markdown_skills returned empty list"
            # Verify all proposed files produced a skill
            if len(skills) < len(proposed_files):
                return False, (
                    f"Expected {len(proposed_files)} skills, loaded {len(skills)}"
                )
        return True, ""
    except Exception as exc:
        return False, str(exc)


# Diff building
def _build_diffs(
    current_skills: dict[str, str],
    proposed_files: dict[str, str],
    changes: list[dict[str, str]],
    eligible: list[SkillProposal],
) -> list[SkillDiff]:
    """Build SkillDiff objects comparing old and new skill contents."""
    # Map target_file -> proposal_id for reference
    target_to_proposal: dict[str, str] = {}
    for p in eligible:
        target_to_proposal[p.target_file] = p.proposal_id

    # Map filename -> change action from LLM output
    change_actions: dict[str, str] = {}
    for c in changes:
        fname = c.get("filename", "")
        if fname:
            change_actions[fname] = c.get("action", "modified")

    diffs: list[SkillDiff] = []
    for fname, new_content in proposed_files.items():
        old_content = current_skills.get(fname)
        if old_content == new_content:
            continue
        action = "modified" if old_content is not None else "created"
        proposal_ref = target_to_proposal.get(fname, "")
        diffs.append(
            SkillDiff(
                filename=fname,
                action=action,
                proposal_ref=proposal_ref,
                before=old_content,
                after=new_content,
            )
        )
    return diffs
