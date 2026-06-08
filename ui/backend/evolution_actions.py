"""Side-effecting evolution action helpers for the UI backend."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException

from app.util.time import beijing_now_iso


def _promote_evolution_run(store: Any, run: dict[str, Any]) -> None:
    role = str(run.get("role") or "").strip()
    if not role:
        raise HTTPException(status_code=400, detail="evolution run has no role")
    version_id = _safe_registry_id(
        str(run.get("candidate_hash") or f"{role}_{run.get('run_id', 'run')}_candidate")
    )
    proposals = [item for item in run.get("proposals", []) or [] if isinstance(item, dict)]
    proposal_ids = [str(item.get("proposal_id")) for item in proposals if item.get("proposal_id")]
    try:
        published = store.registry.publish_skills(
            role,
            _evolution_skill_contents(role, run),
            parent_id=str(run.get("parent_hash") or "") or None,
            source="evolution",
            run_id=str(run.get("run_id") or ""),
            proposal_ids=proposal_ids,
            version_id=version_id,
            set_as_baseline=True,
            expected_current=store.registry.get_baseline(role),
        )
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"failed to promote evolution run: {exc}") from exc
    run["candidate_hash"] = published
    run["published_version_id"] = published
    run["promoted_version_id"] = published
    run["finished_at"] = run.get("finished_at") or beijing_now_iso()


def _reject_evolution_run(store: Any, run: dict[str, Any]) -> None:
    role = str(run.get("role") or "").strip()
    if not role:
        raise HTTPException(status_code=400, detail="evolution run has no role")
    proposals = [item for item in run.get("proposals", []) or [] if isinstance(item, dict)]
    if proposals:
        store.registry.save_rejected(role, proposals, run.get("battle_result") if isinstance(run.get("battle_result"), dict) else None)
    run["rejected_at"] = beijing_now_iso()
    run["finished_at"] = run.get("finished_at") or run["rejected_at"]


def _evolution_skill_contents(role: str, run: dict[str, Any]) -> dict[str, str]:
    run_id = str(run.get("run_id") or "evolution_run")
    proposals = [item for item in run.get("proposals", []) or [] if isinstance(item, dict)]
    diff = [item for item in run.get("diff", []) or [] if isinstance(item, dict)]
    lines = [
        "## Runtime",
        "",
        f"Generated from evolution run `{run_id}`.",
        "",
    ]
    if proposals:
        lines.append("### Accepted proposals")
        for index, proposal in enumerate(proposals, start=1):
            title = proposal.get("section") or proposal.get("target_file") or proposal.get("proposal_id") or f"proposal {index}"
            content = str(proposal.get("content") or proposal.get("rationale") or "").strip()
            lines.extend([f"{index}. {title}", ""])
            if content:
                lines.extend([content, ""])
            if proposal.get("rationale"):
                lines.extend([f"Rationale: {proposal['rationale']}", ""])
    elif diff:
        lines.append("### Applied diff")
        for item in diff:
            after = str(item.get("after") or item.get("content") or "").strip()
            if after:
                lines.extend([after, ""])
    else:
        lines.extend(["No concrete proposal content was available; keep baseline strategy unchanged.", ""])
    content = "\n".join(lines).strip()
    name = _safe_registry_id(f"{role}_{run_id}_skill")
    return {
        "evolution.md": (
            "---\n"
            f"name: {name}\n"
            f"role: {role}\n"
            "applicable_actions:\n"
            "  - speak\n"
            "status: active\n"
            "evolution:\n"
            "  enabled: true\n"
            "  allowed_actions:\n"
            "    - append_rule\n"
            "    - rewrite_section\n"
            "    - deprecate_rule\n"
            "---\n"
            f"{content}\n"
        )
    }


def _safe_registry_id(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value.strip())
    return safe.strip("_-")[:96] or f"version_{uuid.uuid4().hex[:8]}"
