"""Shared helpers for UI backend route modules.

Provides:
  - FastAPI dependency-injection functions for app.state managers (with fallback
    to module-level globals in ui.backend.app for test compatibility)
  - Common utility functions shared across multiple route files
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request


# ---------------------------------------------------------------------------
# Dynamic proxy for DEFAULT_PATHS
#
# Tests monkey-patch ``ui.backend.app.DEFAULT_PATHS`` at runtime.  Route files
# and helper functions that need ``DEFAULT_PATHS`` should use this proxy object
# instead of importing ``DEFAULT`` from ``agent.common.paths`` directly.  The
# proxy resolves the attribute at access time, so patches are always visible.
# ---------------------------------------------------------------------------


class _DefaultPathsProxy:
    """Proxy that forwards attribute access to the current DEFAULT_PATHS."""

    __slots__ = ()

    def __getattr__(self, name: str) -> Any:
        import ui.backend.app as _app_mod
        return getattr(_app_mod.DEFAULT_PATHS, name)

    def __str__(self) -> str:
        import ui.backend.app as _app_mod
        return str(_app_mod.DEFAULT_PATHS)

    def __repr__(self) -> str:
        import ui.backend.app as _app_mod
        return repr(_app_mod.DEFAULT_PATHS)


DEFAULT_PATHS = _DefaultPathsProxy()


# ---------------------------------------------------------------------------
# FastAPI dependency functions for managers
#
# Each dependency first checks ``request.app.state`` (populated by the lifespan
# handler in production).  If the attribute is not set (e.g. when tests use
# ``TestClient(app)`` without a context manager), it falls back to the
# module-level global in ``ui.backend.app``, which tests monkey-patch directly.
# ---------------------------------------------------------------------------


def get_game_manager(request: Request):
    """Dependency: returns the GameManager."""
    try:
        return request.app.state.game_manager
    except AttributeError:
        import ui.backend.app as _app_mod
        return _app_mod.manager


def get_selfplay_manager(request: Request):
    """Dependency: returns the SelfplayManager."""
    try:
        return request.app.state.selfplay_manager
    except AttributeError:
        import ui.backend.app as _app_mod
        return _app_mod.selfplay_manager


def get_version_registry(request: Request):
    """Dependency: returns the VersionRegistry."""
    try:
        return request.app.state.version_registry
    except AttributeError:
        import ui.backend.app as _app_mod
        return _app_mod.version_registry


def get_role_evolution_runner(request: Request):
    """Dependency: returns the RoleEvolutionRunner."""
    try:
        return request.app.state.role_evolution_runner
    except AttributeError:
        import ui.backend.app as _app_mod
        return _app_mod.role_evolution_runner


def get_role_batch_evolution_runner(request: Request):
    """Dependency: returns the RoleBatchEvolutionRunner."""
    try:
        return request.app.state.role_batch_evolution_runner
    except AttributeError:
        import ui.backend.app as _app_mod
        return _app_mod.role_batch_evolution_runner


# ---------------------------------------------------------------------------
# Skill-dir resolution
# ---------------------------------------------------------------------------


def resolve_allowed_skill_dir(raw: str | None) -> str | None:
    """Resolve a skill_dir path and verify it is within an allowed root."""
    if not raw:
        return None
    path = Path(raw)
    candidate = path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()
    allowed_roots = [
        (Path.cwd() / "skills").resolve(),
        (Path.cwd() / "data" / "registry").resolve(),
        (Path.cwd() / "runs").resolve(),
    ]
    for root in allowed_roots:
        try:
            candidate.relative_to(root)
            return str(candidate)
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail=f"skill_dir is outside allowed roots: {raw}")


# ---------------------------------------------------------------------------
# Storage / DB helpers
# ---------------------------------------------------------------------------


def storage_db_path() -> Path:
    """Return the path to the wolf.db SQLite database."""
    return DEFAULT_PATHS.data_dir / "wolf.db"


def read_leaderboard_entries_from_db() -> list[dict[str, Any]]:
    """Read leaderboard entries from the SQLite database."""
    db_path = storage_db_path()
    if not db_path.exists():
        return []

    from storage.leaderboard_store import LeaderboardStore
    from storage.schema import get_connection

    conn = get_connection(db_path)
    try:
        return LeaderboardStore(conn).list_entries()
    finally:
        conn.close()


def read_jsonl(path: Path, *, with_index: bool = False) -> list[dict[str, Any]]:
    """Read a JSONL file and return a list of parsed objects."""
    _log = logging.getLogger(__name__)
    lines: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            _log.warning("Corrupt JSONL line %d in %s", index, path)
            continue
        if with_index and isinstance(value, dict):
            value.setdefault("index", index)
        lines.append(value)
    return lines


def archive_decisions(archive: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract decisions from an archive dict, adding index."""
    decisions = archive.get("decisions", [])
    return [
        {**d, "index": idx}
        for idx, d in enumerate(decisions, start=1)
    ]


def get_leaderboard_paths() -> list[Path]:
    """Return the current _LEADERBOARD_PATHS from ui.backend.app (supports test patching)."""
    import ui.backend.app as _app_mod
    return _app_mod._LEADERBOARD_PATHS


# ---------------------------------------------------------------------------
# Game event / decision readers
# ---------------------------------------------------------------------------


def read_game_events(game_dir: Path) -> list[dict[str, Any]] | None:
    """Read game events from DB or JSONL fallback."""
    from storage.replay import read_events_for_artifact

    events = read_events_for_artifact(
        storage_db_path(),
        game_dir,
        root=DEFAULT_PATHS.runs_dir,
    )
    if events is not None:
        return events
    for name in ("game_events.jsonl", "events.jsonl"):
        path = game_dir / name
        if path.exists():
            return read_jsonl(path)
    return None


def read_game_decisions(game_dir: Path) -> list[dict[str, Any]] | None:
    """Read game decisions from DB or archive.json fallback."""
    from storage.replay import read_decisions_for_artifact

    decisions = read_decisions_for_artifact(
        storage_db_path(),
        game_dir,
        root=DEFAULT_PATHS.runs_dir,
    )
    if decisions is not None:
        return decisions
    archive_path = game_dir / "archive.json"
    if archive_path.exists():
        try:
            return archive_decisions(json.loads(archive_path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            logging.getLogger(__name__).warning("Corrupt archive.json in %s", game_dir)
            return None
    return None


def list_games_in_run(run_id: str, run_dir: Path) -> dict[str, Any]:
    """List all games in a run directory with basic info."""
    games_dir = run_dir / "games"
    if not games_dir.exists():
        return {"run_id": run_id, "games": []}
    game_dirs = sorted(g for g in games_dir.iterdir() if g.is_dir())
    games: list[dict[str, Any]] = []
    for gdir in game_dirs:
        game_id = gdir.name
        meta_path = gdir / "meta.json"
        info: dict[str, Any] = {"game_id": game_id}
        info["in_progress"] = not meta_path.exists()
        events = read_game_events(gdir)
        if events is not None:
            info["event_count"] = len(events)
            if events:
                last = events[-1]
                payload = last.get("payload") or {}
                info["winner"] = payload.get("winner")
                info["day"] = last.get("day")
                info["phase"] = last.get("phase")
        else:
            info["event_count"] = 0
        games.append(info)
    return {"run_id": run_id, "games": games}


# ---------------------------------------------------------------------------
# Role-evolution path helpers
# ---------------------------------------------------------------------------


def role_evolution_roots(role_evolution_runner) -> list[Path]:
    """Return the list of root directories where evolution runs are stored."""
    roots = [Path(str(DEFAULT_PATHS.evolution_dir))]

    result: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve()
        if resolved not in seen:
            seen.add(resolved)
            result.append(root)
    return result


def resolve_role_evolution_training_run_dir(
    run_id: str,
    role_evolution_runner,
) -> Path | None:
    """Find the nested selfplay run directory for role-evolution training games."""
    tracked = role_evolution_runner.get_run(run_id)
    evo_ids: list[str] = []
    training_ids: list[str] = []
    training_output_dirs: list[str] = []
    if tracked is not None:
        if tracked.artifact_run_id:
            evo_ids.append(tracked.artifact_run_id)
        if tracked.training_run_id:
            training_ids.append(tracked.training_run_id)
        if tracked.training_output_dir:
            training_output_dirs.append(tracked.training_output_dir)
        if tracked.run is not None:
            evo_ids.append(tracked.run.run_id)
            if tracked.run.training_run_id:
                training_ids.append(tracked.run.training_run_id)
            if tracked.run.training_output_dir:
                training_output_dirs.append(tracked.run.training_output_dir)
    evo_ids.append(run_id)
    if run_id.startswith("run_"):
        training_ids.append(run_id)

    for raw in dict.fromkeys(training_output_dirs):
        path = Path(raw)
        if path.exists() and (path / "games").exists():
            return path

    for evo_root in role_evolution_roots(role_evolution_runner):
        for evo_id in dict.fromkeys(evo_ids):
            evo_dir = evo_root / evo_id
            if not evo_dir.exists():
                continue
            state_path = evo_dir / "state.json"
            if state_path.exists():
                try:
                    state = json.loads(state_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    state = {}
                training_run_id = state.get("training_run_id")
                if training_run_id:
                    training_ids.append(str(training_run_id))
                training_output_dir = state.get("training_output_dir")
                if training_output_dir:
                    path = Path(str(training_output_dir))
                    if path.exists() and (path / "games").exists():
                        return path
            for training_id in dict.fromkeys(training_ids):
                candidate = evo_dir / training_id
                if candidate.exists() and (candidate / "games").exists():
                    return candidate
            for candidate in sorted(evo_dir.glob("run_*"), reverse=True):
                if candidate.is_dir() and (candidate / "games").exists():
                    return candidate

        if evo_root.exists():
            for candidate in sorted(evo_root.glob(f"*/{run_id}"), reverse=True):
                if candidate.is_dir() and (candidate / "games").exists():
                    return candidate
    return None


def candidate_evolution_dirs(run_id: str, role_evolution_runner) -> list[Path]:
    """Return candidate directories for a given evolution run_id."""
    candidates: list[Path] = []
    for root in role_evolution_roots(role_evolution_runner):
        candidates.append(root / run_id)
    return candidates


def read_optional_dict(path: Path) -> dict[str, Any]:
    """Read a JSON file and return it as a dict, or return {} on any failure."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def read_role_battle_summaries_from_db(role: str) -> list[dict[str, Any]]:
    """Read battle summaries for a role from the SQLite database."""
    db_path = Path(str(DEFAULT_PATHS.data_dir)) / "wolf.db"
    if not db_path.exists():
        return []

    from storage.evolution_store import EvolutionStore
    from storage.schema import get_connection

    conn = get_connection(db_path)
    try:
        return EvolutionStore(conn).list_battle_summaries(role=role)
    finally:
        conn.close()


def read_role_battle_summaries_from_artifacts(
    role: str,
    runner,
) -> list[dict[str, Any]]:
    """Read battle summaries for a role from artifact directories."""
    battle_summaries: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()

    for tracked in runner.get_runs_for_role(role):
        if tracked.run is not None and tracked.run.battle_result is not None:
            battle_summaries.append(tracked.run.battle_result)
            continue
        for evo_dir in candidate_evolution_dirs(tracked.run_id, runner):
            summary_path = evo_dir / "battle_summary.json"
            if summary_path in seen_paths:
                continue
            seen_paths.add(summary_path)
            summary = read_optional_dict(summary_path)
            if summary:
                battle_summaries.append(summary)

    for evo_root in role_evolution_roots(runner):
        if not evo_root.exists():
            continue
        for summary_path in sorted(evo_root.glob("*/battle_summary.json")):
            if summary_path in seen_paths:
                continue
            seen_paths.add(summary_path)
            summary = read_optional_dict(summary_path)
            if str(summary.get("role") or "") == role:
                battle_summaries.append(summary)

    return battle_summaries


def require_battle_side(side: str | None) -> str:
    """Validate that side is 'baseline' or 'candidate'."""
    if side not in {"baseline", "candidate"}:
        raise HTTPException(
            status_code=400,
            detail="side must be 'baseline' or 'candidate' when phase is 'battle'",
        )
    return side


# ---------------------------------------------------------------------------
# Evolution action helpers
# ---------------------------------------------------------------------------


async def apply_batch_evolution_action(
    batch_id: str,
    action: str,
    batch_runner,
) -> dict[str, Any]:
    """Apply an action (promote/reject/stop/terminate) to a batch evolution run."""
    try:
        if action == "promote":
            tracked = await batch_runner.promote_batch(batch_id)
        elif action == "reject":
            tracked = await batch_runner.reject_batch(batch_id)
        elif action == "stop":
            tracked = batch_runner.stop_batch(batch_id)
        elif action == "terminate":
            tracked = batch_runner.terminate_batch(batch_id)
        else:
            raise HTTPException(status_code=400, detail=f"unsupported batch action: {action}")
    except KeyError:
        raise HTTPException(status_code=404, detail="batch not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if tracked is None:
        raise HTTPException(status_code=404, detail="batch not found")
    return tracked.snapshot()


async def apply_role_evolution_action(
    run_id: str,
    action: str,
    runner,
) -> dict[str, Any]:
    """Apply an action (promote/reject/resume/rerun_consolidation/stop/terminate) to a role evolution run."""
    from agent.learning.evolution.pipeline import InvalidRunStateError, BaselineChangedError

    try:
        if action == "promote":
            tracked = await runner.promote_run(run_id)
        elif action == "reject":
            tracked = await runner.reject_run(run_id)
        elif action == "resume":
            tracked = await runner.resume_run(run_id)
        elif action == "rerun_consolidation":
            tracked = await runner.rerun_consolidation(run_id)
        elif action == "stop":
            tracked = runner.stop_run(run_id)
        elif action == "terminate":
            tracked = runner.terminate_run(run_id)
        else:
            raise HTTPException(status_code=400, detail=f"unsupported evolution action: {action}")
    except KeyError:
        raise HTTPException(status_code=404, detail="run not found")
    except InvalidRunStateError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BaselineChangedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if tracked is None:
        raise HTTPException(status_code=404, detail="run not found")
    return tracked.snapshot()
