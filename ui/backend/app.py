from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic import Field

from ui.backend.game_runner import GameManager
from ui.backend.selfplay_runner import SelfplayManager
from ui.backend.role_evolution_runner import RoleEvolutionRunner
from ui.backend.batch_role_evolution_runner import RoleBatchEvolutionRunner
from agent.learning.evolution.pipeline import InvalidRunStateError, BaselineChangedError
from agent.common.paths import DEFAULT as DEFAULT_PATHS


class StartGameRequest(BaseModel):
    seed: int | None = None
    max_days: int = Field(default=20, ge=1, le=100)
    enable_sheriff: bool = True
    skill_dir: str | None = None
    player_count: int = Field(default=12, ge=12, le=12)
    role_versions: dict[str, str] | None = None  # {role: hash} per-role version selection


class SelfplayRequest(BaseModel):
    num_games: int = Field(default=10, ge=1, le=100)
    agent_version: str | None = None
    skill_dir: str | None = None
    max_days: int = Field(default=20, ge=1, le=100)
    enable_sheriff: bool = True
    enable_batch_dream: bool = False
    game_concurrency: int = Field(default=1, ge=1, le=20)
    llm_concurrency: int = Field(default=5, ge=1, le=100)
    llm_rpm: int = Field(default=60, ge=1, le=600)
    label: str | None = None


class RoleEvolutionStartRequest(BaseModel):
    role: str
    training_games: int = Field(default=20, ge=1, le=100)
    battle_games: int = Field(default=10, ge=1, le=100)
    game_concurrency: int = Field(default=1, ge=1, le=20)
    llm_concurrency: int = Field(default=5, ge=1, le=100)
    llm_rpm: int = Field(default=60, ge=1, le=600)


class RoleEvolutionBatchStartRequest(BaseModel):
    roles: list[str] = Field(min_length=1)
    training_games: int = Field(default=20, ge=1, le=100)
    battle_games: int = Field(default=10, ge=1, le=100)
    role_concurrency: int = Field(default=2, ge=1, le=20)
    game_concurrency: int = Field(default=1, ge=1, le=20)
    llm_concurrency: int = Field(default=5, ge=1, le=100)
    llm_rpm: int = Field(default=60, ge=1, le=600)


def _default_version_store():
    from agent.learning.evolution.store import VersionStore
    return VersionStore()


manager = GameManager()
selfplay_manager = SelfplayManager()
version_store = _default_version_store()
role_evolution_runner = RoleEvolutionRunner(store=version_store)
role_batch_evolution_runner = RoleBatchEvolutionRunner(store=version_store)
app = FastAPI(title="521wolf UI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _on_startup() -> None:
    selfplay_manager.restore_runs()
    role_evolution_runner.recover_on_startup()
    role_evolution_runner.restore_runs()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/games")
def list_games() -> dict[str, Any]:
    return {"games": manager.list_games()}


@app.post("/api/games", status_code=201)
async def start_game(request: StartGameRequest | None = None) -> dict[str, Any]:
    try:
        role_skill_dirs = None
        if request is not None and request.role_versions:
            role_skill_dirs = {}
            for role, hash_val in request.role_versions.items():
                role_skill_dirs[role] = version_store.get_skill_dir(role, hash_val)
        game = await manager.start_game(
            seed=request.seed if request is not None else None,
            max_days=request.max_days if request is not None else 20,
            enable_sheriff=request.enable_sheriff if request is not None else True,
            skill_dir=_resolve_allowed_skill_dir(request.skill_dir) if request is not None else None,
            player_count=request.player_count if request is not None else 12,
            role_skill_dirs=role_skill_dirs,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return manager.snapshot(game, include_events=False)


@app.get("/api/games/{game_id}")
def get_game(game_id: str) -> dict[str, Any]:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    return manager.snapshot(game)


@app.get("/api/games/{game_id}/events")
async def stream_game_events(game_id: str) -> StreamingResponse:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")

    async def event_stream():
        queue = await manager.subscribe(game)
        try:
            while True:
                item = await queue.get()
                event_name = item["kind"]
                payload = json.dumps(item["payload"], ensure_ascii=False)
                yield f"event: {event_name}\ndata: {payload}\n\n"
                if event_name in {"done", "error"}:
                    break
        finally:
            manager.unsubscribe(game, queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/api/games/{game_id}/archive")
def get_game_archive(game_id: str) -> dict[str, Any]:
    """Read the full trace archive for a game (prompts, decisions, etc.)."""
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    archive = manager.read_archive(game_id)
    if archive is None:
        raise HTTPException(status_code=404, detail="archive not available")
    return archive


@app.get("/api/games/{game_id}/review")
def get_game_review(game_id: str) -> dict[str, Any]:
    game = manager.get_game(game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="game not found")
    review = manager.build_review(game_id)
    if review is None:
        raise HTTPException(status_code=404, detail="review not available")
    return review


# ── Leaderboard ───────────────────────────────────────────────────────────────


_LEADERBOARD_PATHS = [
    DEFAULT_PATHS.runs_dir / "evolution" / "leaderboard.json",
    DEFAULT_PATHS.data_dir / "leaderboard.json",
]


@app.get("/api/leaderboards")
def list_leaderboards() -> dict[str, Any]:
    """Read leaderboard from known output paths."""
    for path in _LEADERBOARD_PATHS:
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(data, list):
                return {"entries": data, "source": str(path)}
            if isinstance(data, dict) and "entries" in data:
                return {**data, "source": str(path)}
    return {"entries": [], "source": None}


def _resolve_allowed_skill_dir(raw: str | None) -> str | None:
    if not raw:
        return None
    path = Path(raw)
    candidate = path.resolve() if path.is_absolute() else (Path.cwd() / path).resolve()
    allowed_roots = [
        (Path.cwd() / "skills").resolve(),
        (Path.cwd() / "data" / "versions").resolve(),
        (Path.cwd() / "runs").resolve(),
    ]
    for root in allowed_roots:
        try:
            candidate.relative_to(root)
            return str(candidate)
        except ValueError:
            continue
    raise HTTPException(status_code=400, detail=f"skill_dir is outside allowed roots: {raw}")


# ── Selfplay Batch Runs ──────────────────────────────────────────────────────


@app.post("/api/selfplay", status_code=201)
async def start_selfplay(request: SelfplayRequest | None = None) -> dict[str, Any]:
    """Start a batch selfplay run in the background. Returns the run_id."""
    if request is None:
        request = SelfplayRequest()
    agent_version = request.agent_version or "agent"
    skill_dir = _resolve_allowed_skill_dir(request.skill_dir)
    run = await selfplay_manager.start_run(
        num_games=request.num_games,
        agent_version=agent_version,
        skill_dir=skill_dir,
        max_days=request.max_days,
        enable_sheriff=request.enable_sheriff,
        enable_batch_dream=request.enable_batch_dream,
        game_concurrency=request.game_concurrency,
        llm_concurrency=request.llm_concurrency,
        llm_rpm=request.llm_rpm,
        label=request.label,
    )
    return run.snapshot()


@app.get("/api/selfplay")
def list_selfplays() -> dict[str, Any]:
    """List all selfplay runs (active and completed)."""
    return {"runs": selfplay_manager.list_runs()}


@app.get("/api/selfplay/{run_id}")
def get_selfplay(run_id: str) -> dict[str, Any]:
    """Get status and progress of a specific selfplay run."""
    run = selfplay_manager.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return run.snapshot()


@app.post("/api/selfplay/{run_id}/stop")
def stop_selfplay(run_id: str) -> dict[str, Any]:
    """Stop a running selfplay task (can be resumed later)."""
    run = selfplay_manager.stop_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return run.snapshot()


@app.post("/api/selfplay/{run_id}/resume")
def resume_selfplay(run_id: str) -> dict[str, Any]:
    """Resume a paused or interrupted selfplay task."""
    run = selfplay_manager.resume_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return run.snapshot()


@app.post("/api/selfplay/{run_id}/terminate")
def terminate_selfplay(run_id: str) -> dict[str, Any]:
    """Permanently stop a selfplay run."""
    run = selfplay_manager.terminate_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return run.snapshot()


# ── Selfplay Game Detail ─────────────────────────────────────────────────────


def _resolve_selfplay_run_dir(run_id: str) -> Path | None:
    """Find the output directory for a selfplay run."""
    run = selfplay_manager.get_run(run_id)
    if run is not None and run.artifact_run_id:
        path = Path("runs/selfplay") / run.artifact_run_id
        if path.exists():
            return path
    # Fallback to direct path
    path = Path("runs/selfplay") / run_id
    return path if path.exists() else None


def _read_jsonl(path: Path, *, with_index: bool = False) -> list[dict[str, Any]]:
    """Read a JSONL file and return a list of parsed objects."""
    lines: list[dict[str, Any]] = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if line:
            value = json.loads(line)
            if with_index and isinstance(value, dict):
                value.setdefault("index", index)
            lines.append(value)
    return lines


def _list_games_in_run(run_id: str, run_dir: Path) -> dict[str, Any]:
    games_dir = run_dir / "games"
    if not games_dir.exists():
        return {"run_id": run_id, "games": []}
    game_dirs = sorted(g for g in games_dir.iterdir() if g.is_dir())
    games: list[dict[str, Any]] = []
    for gdir in game_dirs:
        game_id = gdir.name
        events_path = gdir / "game_events.jsonl"
        meta_path = gdir / "meta.json"
        info: dict[str, Any] = {"game_id": game_id}
        info["in_progress"] = not meta_path.exists()
        if events_path.exists():
            events = _read_jsonl(events_path)
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


@app.get("/api/selfplay/{run_id}/games")
def list_selfplay_games(run_id: str) -> dict[str, Any]:
    """List all games in a selfplay run with basic info."""
    run_dir = _resolve_selfplay_run_dir(run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    return _list_games_in_run(run_id, run_dir)


@app.get("/api/selfplay/{run_id}/games/{game_id}/events")
def get_selfplay_game_events(run_id: str, game_id: str) -> dict[str, Any]:
    """Get all events for a specific game in a selfplay run."""
    run_dir = _resolve_selfplay_run_dir(run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    events_path = run_dir / "games" / game_id / "game_events.jsonl"
    if not events_path.exists():
        raise HTTPException(status_code=404, detail="game events not found")
    events = _read_jsonl(events_path)
    return {"run_id": run_id, "game_id": game_id, "events": events}


@app.get("/api/selfplay/{run_id}/games/{game_id}/decisions")
def get_selfplay_game_decisions(run_id: str, game_id: str) -> dict[str, Any]:
    """Get agent decisions for a specific game."""
    run_dir = _resolve_selfplay_run_dir(run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    decisions_path = run_dir / "games" / game_id / "agent_decisions.jsonl"
    if not decisions_path.exists():
        raise HTTPException(status_code=404, detail="game decisions not found")
    decisions = _read_jsonl(decisions_path, with_index=True)
    return {"run_id": run_id, "game_id": game_id, "decisions": decisions}


@app.get("/api/selfplay/{run_id}/games/{game_id}/archive")
def get_selfplay_game_archive(run_id: str, game_id: str) -> dict[str, Any]:
    """Get full archive for a specific game."""
    run_dir = _resolve_selfplay_run_dir(run_id)
    if run_dir is None:
        raise HTTPException(status_code=404, detail="selfplay run not found")
    archive_path = run_dir / "games" / game_id / "archive.json"
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail="game archive not found")
    return json.loads(archive_path.read_text(encoding="utf-8"))


def _resolve_role_evolution_training_run_dir(run_id: str) -> Path | None:
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

    evo_root = DEFAULT_PATHS.evolution_dir
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



# ── Role Evolution ──────────────────────────────────────────────────────────


def register_role_evolution_routes(
    app: FastAPI,
    runner: RoleEvolutionRunner,
    batch_runner: RoleBatchEvolutionRunner,
) -> None:
    """Register all role-evolution and role-version routes on *app*."""

    # -- Role versions -------------------------------------------------------

    @app.get("/api/roles")
    def list_roles() -> dict[str, Any]:
        """List all roles that have stored versions."""
        roles = runner.store.list_roles()
        return {"roles": roles}

    @app.get("/api/roles/{role}/versions")
    def list_role_versions(role: str) -> dict[str, Any]:
        """List all versions for a role."""
        try:
            versions = runner.store.list_versions(role)
            baseline = runner.store.get_baseline(role)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"role '{role}' not found")
        result = []
        for v in versions:
            d = v.to_dict()
            d["is_baseline"] = v.hash == baseline.hash
            result.append(d)
        return {"role": role, "versions": result}

    @app.get("/api/roles/{role}/versions/{hash}")
    def get_role_version(role: str, hash: str) -> dict[str, Any]:
        """Get full detail of a specific role version."""
        try:
            version = runner.store.load_version(role, hash)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"version {role}/{hash} not found",
            )
        data = version.to_dict()
        data["kind"] = "role_version"
        data["schema_version"] = 1
        return data

    @app.get("/api/roles/{role}/leaderboard")
    def role_leaderboard(role: str) -> dict[str, Any]:
        """Return the role evolution leaderboard for a role."""
        from agent.learning.evolution.leaderboard import aggregate_role_leaderboard

        # Collect battle summaries from completed runs
        battle_summaries: list[dict] = []
        for tracked in runner.get_runs_for_role(role):
            # Try in-memory first
            if tracked.run is not None and tracked.run.battle_result is not None:
                battle_summaries.append(tracked.run.battle_result)
            else:
                # Fall back to disk
                evo_dir = runner.store.base_dir / "runs" / "evolution" / tracked.run_id
                summary_path = evo_dir / "battle_summary.json"
                if summary_path.exists():
                    try:
                        summary = json.loads(summary_path.read_text(encoding="utf-8"))
                        battle_summaries.append(summary)
                    except Exception:
                        pass

        entries = aggregate_role_leaderboard(
            role=role,
            battle_summaries=battle_summaries,
            store=runner.store,
        )
        return {
            "kind": "role_leaderboard",
            "schema_version": 1,
            "role": role,
            "entries": [e.to_dict() for e in entries],
        }

    @app.post("/api/roles/{role}/rollback/{hash}")
    async def rollback_baseline(role: str, hash: str) -> dict[str, Any]:
        """Rollback the baseline for a role to a specific version hash."""
        # Verify the target hash exists
        try:
            runner.store.load_version(role, hash)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"version {role}/{hash} not found",
            )

        try:
            history = runner.store.get_history(role)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"role '{role}' not found",
            )

        # CAS update
        success = await runner.store.set_baseline(
            role=role,
            target_hash=hash,
            expected_current=history.baseline,
        )
        if not success:
            raise HTTPException(
                status_code=409,
                detail="baseline changed concurrently; retry",
            )
        return {
            "kind": "role_rollback",
            "schema_version": 1,
            "role": role,
            "new_baseline": hash,
        }

    # -- Role evolution runs -------------------------------------------------

    @app.get("/api/role-evolution")
    def list_role_evolution_runs() -> dict[str, Any]:
        """List all tracked role evolution runs."""
        return {
            "kind": "role_evolution_runs",
            "schema_version": 1,
            "runs": runner.list_runs(),
        }

    @app.get("/api/role-evolution/batches")
    def list_role_batch_evolution_runs() -> dict[str, Any]:
        """List all tracked batch role evolution runs."""
        return {
            "kind": "role_batch_evolution_runs",
            "schema_version": 1,
            "batches": batch_runner.list_batches(),
        }

    @app.post("/api/role-evolution/batch/start", status_code=201)
    async def start_role_batch_evolution(request: RoleEvolutionBatchStartRequest) -> dict[str, Any]:
        """Start a batch role evolution run."""
        missing: list[str] = []
        for role in request.roles:
            try:
                runner.store.get_baseline(role)
            except FileNotFoundError:
                missing.append(role)
        if missing:
            raise HTTPException(
                status_code=404,
                detail=f"roles have no baseline version: {', '.join(missing)}",
            )
        try:
            tracked = await batch_runner.start_batch(
                roles=request.roles,
                training_games=request.training_games,
                battle_games=request.battle_games,
                role_concurrency=request.role_concurrency,
                game_concurrency=request.game_concurrency,
                llm_concurrency=request.llm_concurrency,
                llm_rpm=request.llm_rpm,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return tracked.snapshot()

    @app.get("/api/role-evolution/batch/{batch_id}/status")
    def get_role_batch_evolution_status(batch_id: str) -> dict[str, Any]:
        tracked = batch_runner.get_batch(batch_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return tracked.snapshot()

    @app.post("/api/role-evolution/batch/{batch_id}/promote")
    async def promote_role_batch_evolution(batch_id: str) -> dict[str, Any]:
        try:
            tracked = await batch_runner.promote_batch(batch_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="batch not found")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return tracked.snapshot()

    @app.post("/api/role-evolution/batch/{batch_id}/reject")
    async def reject_role_batch_evolution(batch_id: str) -> dict[str, Any]:
        try:
            tracked = await batch_runner.reject_batch(batch_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="batch not found")
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return tracked.snapshot()

    @app.post("/api/role-evolution/batch/{batch_id}/stop")
    def stop_role_batch_evolution(batch_id: str) -> dict[str, Any]:
        tracked = batch_runner.stop_batch(batch_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return tracked.snapshot()

    @app.post("/api/role-evolution/batch/{batch_id}/terminate")
    def terminate_role_batch_evolution(batch_id: str) -> dict[str, Any]:
        tracked = batch_runner.terminate_batch(batch_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="batch not found")
        return tracked.snapshot()

    @app.get("/api/role-evolution/batch/{batch_id}/events")
    async def stream_role_batch_evolution_events(batch_id: str) -> StreamingResponse:
        tracked = batch_runner.get_batch(batch_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="batch not found")

        async def event_stream():
            async for chunk in batch_runner.sse_events(batch_id):
                yield chunk

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @app.post("/api/role-evolution/start", status_code=201)
    async def start_role_evolution(request: RoleEvolutionStartRequest) -> dict[str, Any]:
        """Start a new role evolution run."""
        # Verify the role has a baseline
        try:
            runner.store.get_baseline(request.role)
        except FileNotFoundError:
            raise HTTPException(
                status_code=404,
                detail=f"role '{request.role}' has no baseline version",
            )

        tracked = await runner.start_evolution(
            role=request.role,
            training_games=request.training_games,
            battle_games=request.battle_games,
            game_concurrency=request.game_concurrency,
            llm_concurrency=request.llm_concurrency,
            llm_rpm=request.llm_rpm,
        )
        return tracked.snapshot()

    @app.get("/api/role-evolution/{run_id}/status")
    def get_role_evolution_status(run_id: str) -> dict[str, Any]:
        """Get status of a role evolution run."""
        tracked = runner.get_run(run_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="run not found")
        return tracked.snapshot()

    @app.post("/api/role-evolution/{run_id}/stop")
    def stop_role_evolution(run_id: str) -> dict[str, Any]:
        """Stop a running evolution task (can be resumed)."""
        tracked = runner.stop_run(run_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="run not found")
        return tracked.snapshot()

    @app.post("/api/role-evolution/{run_id}/terminate")
    def terminate_role_evolution(run_id: str) -> dict[str, Any]:
        """Permanently stop an evolution run."""
        tracked = runner.terminate_run(run_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="run not found")
        return tracked.snapshot()

    @app.post("/api/role-evolution/{run_id}/resume")
    async def resume_role_evolution(run_id: str) -> dict[str, Any]:
        """Resume a paused or failed evolution task."""
        try:
            tracked = await runner.resume_run(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        except InvalidRunStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        return tracked.snapshot()

    @app.post("/api/role-evolution/{run_id}/rerun-consolidation")
    async def rerun_role_evolution_consolidation(run_id: str) -> dict[str, Any]:
        """Re-run consolidation on existing training data with updated prompt."""
        try:
            tracked = await runner.rerun_consolidation(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        return tracked.snapshot()

    @app.get("/api/role-evolution/{run_id}/games")
    def list_role_evolution_training_games(run_id: str) -> dict[str, Any]:
        """List training games produced by a role evolution run."""
        run_dir = _resolve_role_evolution_training_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="training run not found")
        return _list_games_in_run(run_id, run_dir)

    @app.get("/api/role-evolution/{run_id}/games/{game_id}/events")
    def get_role_evolution_training_game_events(run_id: str, game_id: str) -> dict[str, Any]:
        run_dir = _resolve_role_evolution_training_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="training run not found")
        events_path = run_dir / "games" / game_id / "game_events.jsonl"
        if not events_path.exists():
            raise HTTPException(status_code=404, detail="game events not found")
        return {
            "run_id": run_id,
            "game_id": game_id,
            "events": _read_jsonl(events_path),
        }

    @app.get("/api/role-evolution/{run_id}/games/{game_id}/decisions")
    def get_role_evolution_training_game_decisions(run_id: str, game_id: str) -> dict[str, Any]:
        run_dir = _resolve_role_evolution_training_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="training run not found")
        decisions_path = run_dir / "games" / game_id / "agent_decisions.jsonl"
        if not decisions_path.exists():
            raise HTTPException(status_code=404, detail="game decisions not found")
        return {
            "run_id": run_id,
            "game_id": game_id,
            "decisions": _read_jsonl(decisions_path, with_index=True),
        }

    @app.get("/api/role-evolution/{run_id}/games/{game_id}/archive")
    def get_role_evolution_training_game_archive(run_id: str, game_id: str) -> dict[str, Any]:
        run_dir = _resolve_role_evolution_training_run_dir(run_id)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="training run not found")
        archive_path = run_dir / "games" / game_id / "archive.json"
        if not archive_path.exists():
            raise HTTPException(status_code=404, detail="game archive not found")
        return json.loads(archive_path.read_text(encoding="utf-8"))

    # -- Battle games ---------------------------------------------------------

    def _resolve_battle_run_dir(run_id: str, side: str) -> Path | None:
        """Find the battle directory for baseline or candidate."""
        evo_dir = runner.store.base_dir / "runs" / "evolution" / run_id / "battle" / side
        if not evo_dir.exists():
            return None
        # Find the run_* directory
        for child in sorted(evo_dir.iterdir(), reverse=True):
            if child.is_dir() and child.name.startswith("run_") and (child / "games").exists():
                return child
        return None

    @app.get("/api/role-evolution/{run_id}/battle/{side}/games")
    def list_battle_games(run_id: str, side: str) -> dict[str, Any]:
        """List battle games for baseline or candidate side."""
        if side not in ("baseline", "candidate"):
            raise HTTPException(status_code=400, detail="side must be 'baseline' or 'candidate'")
        run_dir = _resolve_battle_run_dir(run_id, side)
        if run_dir is None:
            return {"run_id": run_id, "side": side, "games": []}
        result = _list_games_in_run(run_id, run_dir)
        result["side"] = side
        return result

    @app.get("/api/role-evolution/{run_id}/battle/{side}/games/{game_id}/events")
    def get_battle_game_events(run_id: str, side: str, game_id: str) -> dict[str, Any]:
        if side not in ("baseline", "candidate"):
            raise HTTPException(status_code=400, detail="side must be 'baseline' or 'candidate'")
        run_dir = _resolve_battle_run_dir(run_id, side)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="battle run not found")
        events_path = run_dir / "games" / game_id / "game_events.jsonl"
        if not events_path.exists():
            raise HTTPException(status_code=404, detail="game events not found")
        return {"run_id": run_id, "game_id": game_id, "side": side, "events": _read_jsonl(events_path)}

    @app.get("/api/role-evolution/{run_id}/battle/{side}/games/{game_id}/decisions")
    def get_battle_game_decisions(run_id: str, side: str, game_id: str) -> dict[str, Any]:
        if side not in ("baseline", "candidate"):
            raise HTTPException(status_code=400, detail="side must be 'baseline' or 'candidate'")
        run_dir = _resolve_battle_run_dir(run_id, side)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="battle run not found")
        decisions_path = run_dir / "games" / game_id / "agent_decisions.jsonl"
        if not decisions_path.exists():
            raise HTTPException(status_code=404, detail="game decisions not found")
        return {"run_id": run_id, "game_id": game_id, "side": side, "decisions": _read_jsonl(decisions_path, with_index=True)}

    @app.get("/api/role-evolution/{run_id}/battle/{side}/games/{game_id}/archive")
    def get_battle_game_archive(run_id: str, side: str, game_id: str) -> dict[str, Any]:
        if side not in ("baseline", "candidate"):
            raise HTTPException(status_code=400, detail="side must be 'baseline' or 'candidate'")
        run_dir = _resolve_battle_run_dir(run_id, side)
        if run_dir is None:
            raise HTTPException(status_code=404, detail="battle run not found")
        archive_path = run_dir / "games" / game_id / "archive.json"
        if not archive_path.exists():
            raise HTTPException(status_code=404, detail="game archive not found")
        return json.loads(archive_path.read_text(encoding="utf-8"))

    @app.get("/api/role-evolution/{run_id}/diff")
    def get_role_evolution_diff(run_id: str) -> dict[str, Any]:
        """Get the skill diffs produced by a run."""
        tracked = runner.get_run(run_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="run not found")
        # Try in-memory first
        if tracked.run is not None and tracked.run.diff is not None:
            return {
                "kind": "role_evolution_diff",
                "schema_version": 1,
                "run_id": run_id,
                "diffs": [d.to_dict() for d in tracked.run.diff],
            }
        # Fall back to disk
        evo_dir = runner.store.base_dir / "runs" / "evolution" / run_id
        diff_path = evo_dir / "diff.json"
        if diff_path.exists():
            return json.loads(diff_path.read_text(encoding="utf-8"))
        return {
            "kind": "role_evolution_diff",
            "schema_version": 1,
            "run_id": run_id,
            "diffs": [],
        }

    @app.post("/api/role-evolution/{run_id}/promote")
    async def promote_role_evolution(run_id: str) -> dict[str, Any]:
        """Promote a reviewing run's candidate to baseline."""
        try:
            tracked = await runner.promote_run(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        except InvalidRunStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except BaselineChangedError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return tracked.snapshot()

    @app.post("/api/role-evolution/{run_id}/reject")
    async def reject_role_evolution(run_id: str) -> dict[str, Any]:
        """Reject a reviewing run."""
        try:
            tracked = await runner.reject_run(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="run not found")
        except InvalidRunStateError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return tracked.snapshot()

    @app.get("/api/role-evolution/{run_id}/events")
    async def stream_role_evolution_events(run_id: str) -> StreamingResponse:
        """SSE stream of progress events for a role evolution run."""
        tracked = runner.get_run(run_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="run not found")

        async def event_stream():
            async for chunk in runner.sse_events(run_id):
                yield chunk

        return StreamingResponse(event_stream(), media_type="text/event-stream")


register_role_evolution_routes(app, role_evolution_runner, role_batch_evolution_runner)
