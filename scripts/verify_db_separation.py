"""Verify that wolf.db, evolution.db, and registry.db tables are separated.

wolf.db should contain game/play/battle tables only.
evolution.db should contain evolution/learning pipeline tables only.
registry.db should contain role version registry tables only.

Exits 0 if all checks pass, 1 if any fail.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WOLF_DB = ROOT / "data" / "wolf.db"
EVOLUTION_DB = ROOT / "data" / "evolution.db"
REGISTRY_DB = ROOT / "data" / "registry" / "registry.db"

# Tables that MUST NOT appear in wolf.db
WOLF_MUST_NOT_EXIST = [
    "experience_candidates",
    "role_versions",
    "skill_proposals",
    "evolution_runs",
]

# Tables that MUST appear in wolf.db
WOLF_MUST_EXIST = [
    "games",
    "players",
    "decisions",
    "game_events",
    "evaluations",
    "decision_reviews",
    "counterfactuals",
    "reports",
    "evaluation_batches",
    "benchmark_leaderboard",
    "seed_sets",
    "llm_judgments",
]

# Tables that MUST appear in evolution.db
EVOLUTION_MUST_EXIST = [
    "experience_candidates",
    "skill_proposals",
    "evolution_runs",
    "evolution_rounds",
    "candidate_packages",
    "promotion_decisions",
    "rejected_proposals",
    "patterns",
    "situational_records",
    "decision_outcomes",
]

EVOLUTION_MUST_NOT_EXIST = [
    "role_versions",
    "role_current_baseline",
    "role_baseline_history",
    "skill_files",
]

REGISTRY_MUST_EXIST = [
    "role_versions",
    "role_current_baseline",
    "role_baseline_history",
    "skill_files",
    "rejected_proposals",
]

REGISTRY_MUST_NOT_EXIST = [
    "games",
    "players",
    "decisions",
    "game_events",
    "experience_candidates",
    "evolution_runs",
    "skill_proposals",
]


def _get_tables(db_path: Path) -> set[str]:
    """Return the set of user-created table names in a SQLite database."""
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {row[0] for row in rows}
    finally:
        conn.close()


def verify() -> bool:
    passed = True

    # ---- wolf.db checks ----
    print(f"=== wolf.db  ({WOLF_DB}) ===")
    if not WOLF_DB.exists():
        print("  INFO  wolf.db not found -- skipping checks (expected after clean)")
        print()
    else:
        tables = _get_tables(WOLF_DB)
        for name in WOLF_MUST_NOT_EXIST:
            if name in tables:
                print(f"  FAIL  table '{name}' SHOULD NOT exist in wolf.db")
                passed = False
            else:
                print(f"  PASS  table '{name}' correctly absent from wolf.db")
        for name in WOLF_MUST_EXIST:
            if name in tables:
                print(f"  PASS  table '{name}' exists in wolf.db")
            else:
                print(f"  FAIL  table '{name}' MISSING from wolf.db")
                passed = False
        print()

    # ---- evolution.db checks ----
    print(f"=== evolution.db  ({EVOLUTION_DB}) ===")
    if not EVOLUTION_DB.exists():
        print("  INFO  evolution.db not found -- skipping checks (expected after clean)")
        print()
    else:
        tables = _get_tables(EVOLUTION_DB)
        for name in EVOLUTION_MUST_NOT_EXIST:
            if name in tables:
                print(f"  FAIL  table '{name}' SHOULD NOT exist in evolution.db")
                passed = False
            else:
                print(f"  PASS  table '{name}' correctly absent from evolution.db")
        for name in EVOLUTION_MUST_EXIST:
            if name in tables:
                print(f"  PASS  table '{name}' exists in evolution.db")
            else:
                print(f"  FAIL  table '{name}' MISSING from evolution.db")
                passed = False
        print()

    # ---- registry.db checks ----
    print(f"=== registry.db  ({REGISTRY_DB}) ===")
    if not REGISTRY_DB.exists():
        print("  INFO  registry.db not found -- skipping checks (expected after clean before bootstrap)")
        print()
    else:
        tables = _get_tables(REGISTRY_DB)
        for name in REGISTRY_MUST_NOT_EXIST:
            if name in tables:
                print(f"  FAIL  table '{name}' SHOULD NOT exist in registry.db")
                passed = False
            else:
                print(f"  PASS  table '{name}' correctly absent from registry.db")
        for name in REGISTRY_MUST_EXIST:
            if name in tables:
                print(f"  PASS  table '{name}' exists in registry.db")
            else:
                print(f"  FAIL  table '{name}' MISSING from registry.db")
                passed = False
        print()

    # ---- Summary ----
    if passed:
        print("Result: ALL CHECKS PASSED")
    else:
        print("Result: SOME CHECKS FAILED")

    return passed


if __name__ == "__main__":
    ok = verify()
    sys.exit(0 if ok else 1)
