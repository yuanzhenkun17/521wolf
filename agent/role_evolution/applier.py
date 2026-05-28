"""Skill applier — applies consolidation proposals to skill files via LLM.

Takes a ``SkillConsolidation`` (batch of proposals) and the current skill
files, asks the LLM to produce modified files, validates the result through
13 safety checks, smoke-tests via ``load_markdown_skills``, and returns
the new skill contents along with diffs.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from agent.role_evolution.models import (
    SkillConsolidation,
    SkillDiff,
    SkillProposal,
)
from agent.runtime.model import ModelAdapter
from agent.skill_system.loader import load_markdown_skills, parse_front_matter

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 0.5
MAX_SKILL_LENGTH = 5000  # chars per file
MAX_CHANGED_FILES = 5

# Global whitelist — code defines what action types exist.
# Skills declare which subset they allow via evolution.allowed_actions.
GLOBAL_ALLOWED_PROPOSAL_ACTIONS = {
    "append_rule",
    "rewrite_section",
    "deprecate_rule",
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
    errors = _validate_all(current_skills, proposed_files, active, changes)
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


# ---------------------------------------------------------------------------
# Filtering & conflict resolution
# ---------------------------------------------------------------------------


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
            skipped = copy.copy(p)
            skipped.status = "skipped"
            _log.debug("Skipping %s due to conflict", p.proposal_id)
            result.append(skipped)
        else:
            result.append(p)
    return result


# ---------------------------------------------------------------------------
# LLM interaction
# ---------------------------------------------------------------------------


def _build_llm_prompt(
    current_skills: dict[str, str],
    eligible: list[SkillProposal],
    role: str,
) -> str:
    """Build the prompt that asks the LLM to produce modified skill files."""
    parts: list[str] = []
    parts.append(
        "You are a skill-file editor for a Werewolf game AI agent. "
        "Apply the proposals below to the current skill files. "
        "Return ONLY a JSON object with the exact shape:\n"
        '{"files": {"filename.md": "full file content", ...}, '
        '"changes": [{"filename": "file.md", "action": "modified|created", '
        '"description": "brief summary"}]}\n'
    )
    parts.append(f"\nRole: {role}\n")

    parts.append("## Current skill files\n")
    for fname, content in current_skills.items():
        parts.append(f"### {fname}\n```\n{content}\n```\n")

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
    return await model_adapter.complete(messages, name="skill_applier")


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


# ---------------------------------------------------------------------------
# Validation (13 checks)
# ---------------------------------------------------------------------------


def _validate_all(
    current_skills: dict[str, str],
    proposed_files: dict[str, str],
    eligible: list[SkillProposal],
    changes: list[dict[str, str]],
) -> list[str]:
    """Run all 13 validation checks. Returns list of error strings (empty = pass)."""
    errors: list[str] = []
    eligible_targets = {p.target_file for p in eligible}

    # 1. Only modify files targeted by eligible proposals
    for fname in proposed_files:
        if fname not in eligible_targets:
            errors.append(f"File '{fname}' was not targeted by any eligible proposal")

    # 1b. Check proposal action_type against global whitelist and per-skill allowed_actions
    for p in eligible:
        if p.action_type not in GLOBAL_ALLOWED_PROPOSAL_ACTIONS:
            errors.append(f"[{p.target_file}] action_type '{p.action_type}' not in global whitelist")
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
        old_content = current_skills.get(fname, "")

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

        # 6b. evolution field must not be modified by applier
        err = _validate_evolution_unchanged(new_content, old_content)
        if err:
            errors.append(f"[{fname}] {err}")

        # 9. Path safety
        err = _validate_path_safe(fname)
        if err:
            errors.append(err)

        # 10. YAML front matter parseable
        fm = _validate_front_matter(new_content)
        if fm is None:
            errors.append(f"[{fname}] YAML front matter is not parseable")

        # 11. File length limit
        if len(new_content) > MAX_SKILL_LENGTH:
            errors.append(
                f"[{fname}] File length {len(new_content)} exceeds limit {MAX_SKILL_LENGTH}"
            )

        # 13. No other role's private strategy leakage
        err = _validate_no_foreign_strategy_leakage(new_content, eligible)
        if err:
            errors.append(f"[{fname}] {err}")

    # 12. Diff size limit — total changed content bounded by MAX_CHANGED_FILES * MAX_SKILL_LENGTH
    total_new = sum(len(v) for v in proposed_files.values())
    if total_new > MAX_CHANGED_FILES * MAX_SKILL_LENGTH:
        errors.append(
            f"Total output size {total_new} exceeds limit "
            f"{MAX_CHANGED_FILES * MAX_SKILL_LENGTH}"
        )

    return errors


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
    p = Path(path)
    if p.is_absolute():
        return f"Path '{path}' is absolute"
    if ".." in p.parts:
        return f"Path '{path}' contains '..'"
    if p.suffix and p.suffix != ".md":
        return f"Path '{path}' is not a .md file"
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


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Diff building
# ---------------------------------------------------------------------------


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
