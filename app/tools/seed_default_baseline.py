"""Seed default role baselines into the runtime PostgreSQL registry.

Usage:
    uv run python -m app.tools.seed_default_baseline
    uv run python -m app.tools.seed_default_baseline --dry-run
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from app.lib.version import validate_skill_manifests, version_registry_from_env
from storage.interfaces import compute_hash, normalize_skill_path, normalize_skill_text

try:
    from ui.backend.constants import ROLE_ORDER as DEFAULT_ROLE_ORDER
except Exception:
    DEFAULT_ROLE_ORDER = (
        "villager",
        "werewolf",
        "white_wolf_king",
        "seer",
        "witch",
        "hunter",
        "guard",
    )


DEFAULT_SKILL_ROOT = Path("skills/default_baseline")
_URL_SECRET_RE = re.compile(r"(?i)((?:postgresql|postgres|mysql)://[^:/@\s]+:)[^@\s]+(@)")
_KV_SECRET_RE = re.compile(r"(?i)\b(password|pass|pwd|token|secret)=([^\s;]+)")


@dataclass
class RolePlan:
    role: str
    contents: dict[str, str] = field(default_factory=dict)
    planned_version_id: str | None = None
    current_baseline: str | None = None
    current_matches: bool | None = None
    action: str = "pending"
    issues: list[str] = field(default_factory=list)
    published_version_id: str | None = None


def _read_role_contents(skill_root: Path, role: str) -> tuple[dict[str, str], list[str]]:
    role_dir = skill_root / role
    if not role_dir.is_dir():
        return {}, [f"{role}: missing skill directory: {role_dir}"]

    files = sorted(path for path in role_dir.rglob("*.md") if path.is_file())
    if not files:
        return {}, [f"{role}: no .md skill files found under {role_dir}"]

    contents: dict[str, str] = {}
    issues: list[str] = []
    for path in files:
        try:
            rel_path = normalize_skill_path(path.relative_to(role_dir).as_posix())
            content = normalize_skill_text(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            issues.append(f"{role}: {path}: {exc}")
            continue
        if rel_path in contents:
            issues.append(f"{role}: duplicate normalized skill path: {rel_path}")
            continue
        contents[rel_path] = content
    return contents, issues


def _load_local_plans(skill_root: Path, roles: Sequence[str]) -> list[RolePlan]:
    plans: list[RolePlan] = []
    for role in roles:
        plan = RolePlan(role=role)
        plan.contents, read_issues = _read_role_contents(skill_root, role)
        plan.issues.extend(read_issues)
        if plan.contents:
            validation_issues = validate_skill_manifests(role, plan.contents)
            plan.issues.extend(f"{role}: {issue}" for issue in validation_issues)
            try:
                plan.planned_version_id = compute_hash(plan.contents)
            except ValueError as exc:
                plan.issues.append(f"{role}: failed to compute skill hash: {exc}")
        plans.append(plan)
    return plans


def _normalized(contents: dict[str, str]) -> dict[str, str]:
    return {
        normalize_skill_path(path): normalize_skill_text(str(content))
        for path, content in contents.items()
    }


def _safe_error(exc: Exception) -> str:
    text = str(exc)
    text = _URL_SECRET_RE.sub(r"\1***\2", text)
    text = _KV_SECRET_RE.sub(r"\1=***", text)
    return text


def _compare_current_baselines(registry: object, plans: Sequence[RolePlan], *, force: bool) -> None:
    for plan in plans:
        if plan.issues:
            continue
        try:
            baseline = registry.get_baseline(plan.role)  # type: ignore[attr-defined]
            plan.current_baseline = baseline
            if baseline is None:
                plan.action = "publish"
                continue

            current_contents = registry.read_skill_contents(plan.role, baseline)  # type: ignore[attr-defined]
            plan.current_matches = _normalized(current_contents) == plan.contents
            if plan.current_matches:
                if baseline == plan.planned_version_id:
                    plan.action = "skip"
                else:
                    plan.action = "publish_same_content"
                continue

            if force:
                plan.action = "publish_force"
            else:
                plan.action = "blocked"
                plan.issues.append(
                    f"{plan.role}: existing baseline {baseline} has different content; "
                    "rerun with --force to publish default_baseline and switch the baseline"
                )
        except Exception as exc:
            plan.action = "error"
            plan.issues.append(f"{plan.role}: failed to inspect current baseline: {_safe_error(exc)}")


def _print_plan(plans: Sequence[RolePlan], *, dry_run: bool, force: bool) -> None:
    mode = "dry-run" if dry_run else "write"
    print(f"Mode: {mode}, force={str(force).lower()}")
    for plan in plans:
        current = plan.current_baseline or "-"
        planned = plan.planned_version_id or "-"
        file_count = len(plan.contents)
        status = "ERROR" if plan.issues else plan.action.upper()
        print(
            f"{plan.role}: {status}; files={file_count}; "
            f"planned_version={planned}; current_baseline={current}"
        )
        for issue in plan.issues:
            print(f"  - {issue}")


def _publish(registry: object, plans: Sequence[RolePlan]) -> list[str]:
    errors: list[str] = []
    for plan in plans:
        if plan.action == "skip":
            continue
        try:
            current = registry.get_baseline(plan.role)  # type: ignore[attr-defined]
            if current != plan.current_baseline:
                raise RuntimeError(
                    f"current baseline changed from {plan.current_baseline!r} to {current!r}; rerun the seed tool"
                )
            plan.published_version_id = registry.publish_skills(  # type: ignore[attr-defined]
                plan.role,
                plan.contents,
                source="default_baseline",
                set_as_baseline=True,
                expected_current=current,
            )
            plan.action = "published"
        except Exception as exc:
            plan.action = "error"
            errors.append(f"{plan.role}: failed to publish: {_safe_error(exc)}")
    return errors


def _close_registry(registry: object | None) -> None:
    if registry is None:
        return
    close = getattr(registry, "close", None)
    if callable(close):
        close()


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish skills/default_baseline role markdown files to the PostgreSQL version registry.",
    )
    parser.add_argument(
        "--skill-root",
        default=str(DEFAULT_SKILL_ROOT),
        help="Root containing <role>/*.md default baseline skill files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read, validate, and compare baselines without writing PostgreSQL.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow replacing an existing different baseline with the default_baseline snapshot.",
    )
    parser.add_argument(
        "--roles",
        nargs="+",
        default=list(DEFAULT_ROLE_ORDER),
        help="Roles to seed. Defaults to the UI role order.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    skill_root = Path(args.skill_root)
    roles = [str(role).strip() for role in args.roles if str(role).strip()]
    if not roles:
        print("No roles selected.")
        return 2

    plans = _load_local_plans(skill_root, roles)
    local_errors = [issue for plan in plans for issue in plan.issues]
    if local_errors:
        _print_plan(plans, dry_run=args.dry_run, force=args.force)
        print("Aborted before registry access because local skill validation failed.")
        return 1

    registry = None
    try:
        try:
            registry = version_registry_from_env()
        except Exception as exc:
            print(f"Failed to open version registry: {_safe_error(exc)}")
            return 1
        _compare_current_baselines(registry, plans, force=args.force)
        blocked_errors = [issue for plan in plans for issue in plan.issues]
        _print_plan(plans, dry_run=args.dry_run, force=args.force)
        if blocked_errors:
            print("Aborted before publishing because one or more roles require attention.")
            return 1
        if args.dry_run:
            print("Dry-run complete. No PostgreSQL writes were performed.")
            return 0

        publish_errors = _publish(registry, plans)
        for plan in plans:
            if plan.action == "skip":
                print(f"{plan.role}: unchanged; baseline already {plan.current_baseline}")
            elif plan.action == "published":
                print(f"{plan.role}: baseline set to {plan.published_version_id}")
        if publish_errors:
            for error in publish_errors:
                print(error)
            return 1
        print("Default baseline seed complete.")
        return 0
    finally:
        _close_registry(registry)


if __name__ == "__main__":
    raise SystemExit(main())
