"""Collect a read-only evidence snapshot for full local MVP research reports."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

from app.config import DEFAULT_PATHS, LLM_ENV_PATH
from app.tools.run_full_local_samples import DEFAULT_OUTPUT_DIR, _partial_game_progress
from app.util.json import to_jsonable, write_json
from app.util.redaction import redact
from app.util.time import beijing_now_iso
from storage.provider import storage_provider_from_env
from ui.backend.constants import ROLE_ORDER


COUNT_TABLES = {
    "wolf": ["games", "game_events", "decisions", "reports", "decision_reviews", "counterfactuals"],
    "registry": ["role_versions", "role_current_baseline", "role_baseline_history", "rejected_proposals"],
    "evolution": [
        "evolution_runs",
        "skill_proposals",
        "candidate_packages",
        "promotion_decisions",
        "ab_comparison_groups",
        "trust_bundles",
    ],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect full local evidence for mvp-research-report.md.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--manifest", default="", help="Defaults to <output-dir>/manifest.json.")
    parser.add_argument("--output", default="", help="Defaults to <output-dir>/evidence_snapshot.json.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_dotenv(LLM_ENV_PATH, override=False)

    output_dir = Path(args.output_dir)
    manifest_path = Path(args.manifest) if args.manifest else output_dir / "manifest.json"
    output_path = Path(args.output) if args.output else output_dir / "evidence_snapshot.json"

    manifest = _read_json(manifest_path)
    snapshot = collect_snapshot(manifest=manifest, manifest_path=manifest_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(output_path, redact(to_jsonable(snapshot), context="diagnostic"))
    print(json.dumps(redact(to_jsonable(snapshot), context="diagnostic"), ensure_ascii=False, indent=2, default=str))
    return 0


def collect_snapshot(*, manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    provider = storage_provider_from_env(paths=DEFAULT_PATHS)
    benchmark = manifest.get("benchmark") if isinstance(manifest.get("benchmark"), dict) else {}
    batch_id = str(benchmark.get("batch_id") or "").strip()

    snapshot: dict[str, Any] = {
        "kind": "full_local_evidence_snapshot",
        "schema_version": 1,
        "created_at": beijing_now_iso(),
        "manifest_path": str(manifest_path),
        "manifest_status": manifest.get("status"),
        "benchmark": _benchmark_snapshot(manifest, batch_id),
        "counts": {},
        "review": {},
        "registry": {},
        "evolution": {},
    }

    with _open(provider.open_wolf_connection) as conn:
        snapshot["counts"]["wolf"] = _count_tables(conn, COUNT_TABLES["wolf"])
        snapshot["review"] = _review_snapshot(conn)
        if batch_id:
            snapshot["benchmark"]["active_progress"] = _partial_game_progress(batch_id)
            snapshot["benchmark"]["phase_summary"] = _active_phase_summary(conn, batch_id)

    with _open(provider.open_registry_connection) as conn:
        snapshot["counts"]["registry"] = _count_tables(conn, COUNT_TABLES["registry"])
        snapshot["registry"] = _registry_snapshot(conn)

    with _open(provider.open_evolution_connection) as conn:
        snapshot["counts"]["evolution"] = _count_tables(conn, COUNT_TABLES["evolution"])
        snapshot["evolution"] = _evolution_snapshot(conn)

    return snapshot


def _benchmark_snapshot(manifest: dict[str, Any], batch_id: str) -> dict[str, Any]:
    benchmark = manifest.get("benchmark") if isinstance(manifest.get("benchmark"), dict) else {}
    preflight = manifest.get("preflight") if isinstance(manifest.get("preflight"), dict) else {}
    settings = benchmark.get("settings") if isinstance(benchmark.get("settings"), dict) else {}
    parameters = manifest.get("parameters") if isinstance(manifest.get("parameters"), dict) else {}
    agent_runtime = benchmark.get("agent_runtime") if isinstance(benchmark.get("agent_runtime"), dict) else {}
    if not agent_runtime and isinstance(manifest.get("agent_runtime"), dict):
        agent_runtime = manifest["agent_runtime"]
    return {
        "status": benchmark.get("status"),
        "batch_id": batch_id,
        "benchmark_id": benchmark.get("benchmark_id"),
        "started_at": benchmark.get("started_at"),
        "last_heartbeat_at": benchmark.get("last_heartbeat_at"),
        "role_count": benchmark.get("role_count"),
        "completed_roles": benchmark.get("completed_roles"),
        "settings": dict(settings),
        "agent_runtime": dict(agent_runtime),
        "parameters": dict(parameters),
        "preflight_status": preflight.get("status"),
    }


def _review_snapshot(conn: Any) -> dict[str, Any]:
    return {
        "reports": _scalar_count(conn, "reports"),
        "decision_reviews": _scalar_count(conn, "decision_reviews"),
        "counterfactuals": _scalar_count(conn, "counterfactuals"),
        "decision_review_quality": _safe_rows(
            conn,
            "SELECT quality, COUNT(*) AS n FROM decision_reviews GROUP BY quality ORDER BY quality",
        ),
    }


def _registry_snapshot(conn: Any) -> dict[str, Any]:
    current = _safe_rows(
        conn,
        """
        SELECT cb.role, cb.version_id, rv.status, rv.source, rv.created_at
        FROM role_current_baseline cb
        LEFT JOIN role_versions rv ON rv.role = cb.role AND rv.id = cb.version_id
        ORDER BY cb.role
        """,
    )
    if not current:
        current = _safe_rows(
            conn,
            """
            SELECT role, id AS version_id, status, source, created_at
            FROM role_versions
            WHERE status = 'baseline'
            ORDER BY role, created_at
            """,
        )
    by_role = {str(row.get("role")): row for row in current if isinstance(row, dict) and row.get("role")}
    return {
        "baseline_count": len(by_role),
        "baselines": [by_role[role] for role in ROLE_ORDER if role in by_role],
        "missing_baseline_roles": [role for role in ROLE_ORDER if role not in by_role],
        "versions_by_role_status": _safe_rows(
            conn,
            """
            SELECT role, status, COUNT(*) AS n
            FROM role_versions
            GROUP BY role, status
            ORDER BY role, status
            """,
        ),
    }


def _evolution_snapshot(conn: Any) -> dict[str, Any]:
    runs = _safe_rows(
        conn,
        """
        SELECT role, status, COUNT(*) AS n, MAX(started_at) AS latest_started_at, MAX(finished_at) AS latest_finished_at
        FROM evolution_runs
        GROUP BY role, status
        ORDER BY role, status
        """,
    )
    full_run_roles = _safe_rows(
        conn,
        """
        SELECT role, id, status, training_games, battle_games, candidate_hash, started_at, finished_at
        FROM evolution_runs
        WHERE training_games >= 20 AND battle_games >= 10
        ORDER BY started_at DESC
        """,
    )
    by_role = {role: {"full_run_status": "not_started"} for role in ROLE_ORDER}
    for row in full_run_roles:
        role = str(row.get("role") or "")
        if role in by_role and by_role[role]["full_run_status"] == "not_started":
            by_role[role] = {
                "full_run_status": str(row.get("status") or "unknown"),
                "run_id": row.get("id"),
                "training_games": row.get("training_games"),
                "battle_games": row.get("battle_games"),
                "candidate_hash": row.get("candidate_hash"),
                "started_at": row.get("started_at"),
                "finished_at": row.get("finished_at"),
            }
    return {
        "runs_by_role_status": runs,
        "full_per_role_status": by_role,
        "artifact_counts": {
            "skill_proposals": _scalar_count(conn, "skill_proposals"),
            "candidate_packages": _scalar_count(conn, "candidate_packages"),
            "promotion_decisions": _scalar_count(conn, "promotion_decisions"),
            "ab_comparison_groups": _scalar_count(conn, "ab_comparison_groups"),
            "trust_bundles": _scalar_count(conn, "trust_bundles"),
        },
    }


def _active_phase_summary(conn: Any, batch_id: str) -> list[dict[str, Any]]:
    like = f"{batch_id}%"
    return _safe_rows(
        conn,
        """
        SELECT game_id, day, phase, COUNT(*) AS events, MAX(created_at) AS last_event_at
        FROM game_events
        WHERE game_id LIKE ?
        GROUP BY game_id, day, phase
        ORDER BY game_id, day, phase
        """,
        (like,),
    )


def _count_tables(conn: Any, tables: Iterable[str]) -> dict[str, Any]:
    return {table: _scalar_count(conn, table) for table in tables}


def _scalar_count(conn: Any, table: str) -> int | dict[str, str]:
    if table not in {item for values in COUNT_TABLES.values() for item in values}:
        raise ValueError(f"unsupported table: {table}")
    try:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        return int(row["n"] or 0) if row is not None else 0
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}


def _safe_rows(conn: Any, sql: str, params: tuple[Any, ...] | None = None) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(sql, params or ()).fetchall()
        return [dict(row) for row in rows]
    except Exception:
        return []


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


class _open:
    def __init__(self, opener: Any) -> None:
        self._opener = opener
        self._conn: Any = None

    def __enter__(self) -> Any:
        self._conn = self._opener()
        return self._conn

    def __exit__(self, *_exc: Any) -> None:
        if self._conn is not None:
            self._conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
