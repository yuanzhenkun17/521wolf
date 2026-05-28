from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic import Field

from agent.evaluation.leaderboard import LeaderboardEntry
from ui.backend.game_runner import GameManager
from ui.backend.selfplay_runner import SelfplayManager
from ui.backend.role_evolution_runner import RoleEvolutionRunner


class StartGameRequest(BaseModel):
    seed: int | None = None
    max_days: int = Field(default=20, ge=1, le=100)
    enable_sheriff: bool = True
    skill_dir: str | None = None
    player_count: int = Field(default=12, ge=12, le=12)


class SelfplayRequest(BaseModel):
    num_games: int = Field(default=10, ge=1, le=100)
    agent_version: str | None = None
    skill_dir: str | None = None
    max_days: int = Field(default=20, ge=1, le=100)
    enable_sheriff: bool = True
    enable_batch_dream: bool = False
    label: str | None = None


class RoleEvolutionStartRequest(BaseModel):
    role: str
    training_games: int = Field(default=20, ge=1, le=100)
    battle_games: int = Field(default=10, ge=1, le=100)


def _default_version_store():
    from agent.role_evolution.store import VersionStore
    return VersionStore(Path("data/role_versions"))


manager = GameManager()
selfplay_manager = SelfplayManager()
role_evolution_runner = RoleEvolutionRunner(store=_default_version_store())
app = FastAPI(title="521wolf UI Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/games")
def list_games() -> dict[str, Any]:
    return {"games": manager.list_games()}


@app.post("/api/games", status_code=201)
async def start_game(request: StartGameRequest | None = None) -> dict[str, Any]:
    try:
        game = await manager.start_game(
            seed=request.seed if request is not None else None,
            max_days=request.max_days if request is not None else 20,
            enable_sheriff=request.enable_sheriff if request is not None else True,
            skill_dir=_resolve_allowed_skill_dir(request.skill_dir) if request is not None else None,
            player_count=request.player_count if request is not None else 12,
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
    """Read the full trace archive for a game (ToT candidates, prompts, etc.)."""
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
    Path("runs/version_battle/leaderboard.json"),
    Path("logs/version_battle/leaderboard.json"),
    Path("data/version_battle/leaderboard.json"),
    Path("leaderboard.json"),
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
        (Path.cwd() / "agent_versions").resolve(),
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


# ── Skill Proposals / Patches / Dreams / Memory Candidates ────────────────────


_DATA_DIR = Path("data")
_PROPOSAL_DIR = _DATA_DIR / "skill_proposals"
_PATCH_DIR = _DATA_DIR / "skill_patches"
_MEMORY_CANDIDATE_DIR = _DATA_DIR / "memory_candidates"
_DREAM_DIR = _DATA_DIR / "dreams"


def _scan_json_files(directory: Path, pattern: str) -> list[dict[str, Any]]:
    """Yield parsed JSON objects from every file matching *pattern* under *directory*.

    Each file may contain a single object or a list of objects.
    Missing directories return an empty list.
    """
    if not directory.is_dir():
        return []
    results: list[dict[str, Any]] = []
    for path in sorted(directory.glob(pattern)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, list):
            results.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            results.append(data)
    return results


@app.get("/api/proposals")
def list_proposals(role: str | None = None) -> dict[str, Any]:
    """List all skill proposals, optionally filtered by role."""
    if role:
        items = _scan_json_files(_PROPOSAL_DIR / role, "proposal_*.json")
    else:
        items = []
        if _PROPOSAL_DIR.is_dir():
            for subdir in sorted(_PROPOSAL_DIR.iterdir()):
                if subdir.is_dir():
                    items.extend(_scan_json_files(subdir, "proposal_*.json"))
    # Return summary fields only
    summaries = [
        {
            "proposal_id": item.get("proposal_id"),
            "role": item.get("role"),
            "skill": item.get("skill"),
            "operation": item.get("operation"),
            "status": item.get("status"),
            "confidence": item.get("confidence"),
            "created_at": item.get("created_at"),
        }
        for item in items
    ]
    return {"proposals": summaries}


@app.get("/api/proposals/patches")
def list_patches() -> dict[str, Any]:
    """List all applied skill patches."""
    items: list[dict[str, Any]] = []
    if _PATCH_DIR.is_dir():
        for subdir in sorted(_PATCH_DIR.iterdir()):
            if subdir.is_dir():
                items.extend(_scan_json_files(subdir, "patch_*.json"))
    return {"patches": items}


@app.get("/api/proposals/{proposal_id}")
def get_proposal(proposal_id: str) -> dict[str, Any]:
    """Get full detail of a specific proposal by its ID."""
    if _PROPOSAL_DIR.is_dir():
        for subdir in sorted(_PROPOSAL_DIR.iterdir()):
            if not subdir.is_dir():
                continue
            for item in _scan_json_files(subdir, "proposal_*.json"):
                if item.get("proposal_id") == proposal_id:
                    return item
    raise HTTPException(status_code=404, detail="proposal not found")


@app.get("/api/memory-candidates")
def list_memory_candidates(role: str | None = None) -> dict[str, Any]:
    """List long-term memory candidates."""
    if not _MEMORY_CANDIDATE_DIR.is_dir():
        return {"candidates": []}
    results: list[dict[str, Any]] = []
    pattern = f"{role}.json" if role else "*.json"
    for path in sorted(_MEMORY_CANDIDATE_DIR.glob(pattern)):
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        results.append({
            "role": data.get("role", path.stem),
            "generated_at": data.get("generated_at"),
            "source_card_count": data.get("source_card_count", 0),
            "win_rate": data.get("win_rate", 0.0),
            "avg_score": data.get("avg_score", 0.0),
            "strategy_count": len(data.get("effective_strategies", [])),
            "mistake_count": len(data.get("recurring_mistakes", [])),
        })
    return {"candidates": results}


@app.get("/api/dreams")
def list_dreams(role: str | None = None) -> dict[str, Any]:
    """List dream reports."""
    if not _DREAM_DIR.is_dir():
        return {"dreams": []}
    items: list[dict[str, Any]] = []
    if role:
        items = _scan_json_files(_DREAM_DIR / role, "dream_*.json")
    else:
        for subdir in sorted(_DREAM_DIR.iterdir()):
            if subdir.is_dir():
                items.extend(_scan_json_files(subdir, "dream_*.json"))
    # Return summary fields
    summaries = [
        {
            "role": item.get("role"),
            "generated_at": item.get("generated_at"),
            "source_card_count": item.get("source_card_count", 0),
            "insight_count": len(item.get("insights", [])),
            "proposal_count": len(item.get("skill_edit_proposals", [])),
        }
        for item in items
    ]
    return {"dreams": summaries}


# ── Role Evolution ──────────────────────────────────────────────────────────


def register_role_evolution_routes(app: FastAPI, runner: RoleEvolutionRunner) -> None:
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
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"role '{role}' not found")
        return {
            "role": role,
            "versions": [v.to_dict() for v in versions],
        }

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
        from agent.role_evolution.leaderboard import aggregate_role_leaderboard

        # Collect battle summaries from completed runs
        battle_summaries: list[dict] = []
        for tracked in runner.get_runs_for_role(role):
            if tracked.run is not None and tracked.run.battle_result is not None:
                battle_summaries.append(tracked.run.battle_result)

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
        )
        return tracked.snapshot()

    @app.get("/api/role-evolution/{run_id}/status")
    def get_role_evolution_status(run_id: str) -> dict[str, Any]:
        """Get status of a role evolution run."""
        tracked = runner.get_run(run_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="run not found")
        return tracked.snapshot()

    @app.get("/api/role-evolution/{run_id}/diff")
    def get_role_evolution_diff(run_id: str) -> dict[str, Any]:
        """Get the skill diffs produced by a run."""
        tracked = runner.get_run(run_id)
        if tracked is None:
            raise HTTPException(status_code=404, detail="run not found")
        if tracked.run is None or tracked.run.diff is None:
            return {
                "kind": "role_evolution_diff",
                "schema_version": 1,
                "run_id": run_id,
                "diffs": [],
            }
        return {
            "kind": "role_evolution_diff",
            "schema_version": 1,
            "run_id": run_id,
            "diffs": [d.to_dict() for d in tracked.run.diff],
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


register_role_evolution_routes(app, role_evolution_runner)
