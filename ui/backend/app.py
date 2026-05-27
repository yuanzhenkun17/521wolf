from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agent.versioning.manifest import (
    AgentVersionManifest,
    load_manifest,
    evaluate_promotion,
    create_agent_version,
    resolve_manifest_path,
)
from agent.evaluation.leaderboard import LeaderboardEntry
from ui.backend.game_runner import GameManager
from ui.backend.evolution_runner import EvolutionManager
from ui.backend.mixed_battle_runner import MixedBattleManager
from ui.backend.selfplay_runner import SelfplayManager


class StartGameRequest(BaseModel):
    seed: int | None = None
    max_days: int = 20
    enable_sheriff: bool = True
    skill_dir: str | None = None
    player_count: int = 12


class SelfplayRequest(BaseModel):
    num_games: int = 10
    agent_version: str | None = None
    skill_dir: str | None = None
    max_days: int = 20
    enable_sheriff: bool = True
    enable_batch_dream: bool = False
    label: str | None = None


class EvolutionRequest(BaseModel):
    base_version: str
    candidate_version: str
    training_games: int = 5
    battle_games: int = 20
    training_seed_start: int = 1
    battle_seed_start: int = 1001
    max_days: int = 20
    enable_dream: bool = True
    enable_skill_proposals: bool = True
    auto_apply_skill_proposals: bool = True
    min_score_improvement: float = 0.05
    max_win_rate_drop: float = 0.10
    notes: str = ""


class MixedBattleRequest(BaseModel):
    wolves_version: str
    villagers_version: str
    games_per_side: int = 5
    seed_start: int = 1
    max_days: int = 20
    enable_review: bool = True


class CreateVersionRequest(BaseModel):
    name: str
    base: str | None = None
    notes: str = ""
    # Model config
    provider: str = "volcengine"
    model: str = "doubao-seed-2.0-pro"
    temperature: float = 0.7
    max_tokens: int = 2048
    base_url: str = ""
    api_key: str = ""
    # Runtime config
    tot_enabled: bool = True
    got_enabled: bool = True
    got_trigger_threshold: float = 0.3
    # Evolution config
    batch_dream_enabled: bool = True


manager = GameManager()
selfplay_manager = SelfplayManager()
evolution_manager = EvolutionManager()
mixed_battle_manager = MixedBattleManager()
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
            skill_dir=request.skill_dir if request is not None else None,
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


# ── Version Management ────────────────────────────────────────────────────────

_VERSIONS_DIRS = [
    Path("data/versions"),
    Path("agent_versions"),
]


def _find_manifests() -> list[Path]:
    """Find all manifest.json files across known version directories."""
    results: list[Path] = []
    for root in _VERSIONS_DIRS:
        if root.is_dir():
            results.extend(sorted(root.glob("*/manifest.json")))
    return results


def _find_manifest_for_version(version_id: str) -> Path | None:
    """Locate the manifest.json for a given version_id."""
    for root in _VERSIONS_DIRS:
        candidate = root / version_id / "manifest.json"
        if candidate.exists():
            return candidate
    return None


def _manifest_summary(manifest: AgentVersionManifest) -> dict[str, Any]:
    return {
        "version_id": manifest.version,
        "label": manifest.display_name or manifest.version,
        "skill_dir": manifest.paths.skills,
        "status": manifest.status.value,
        "created_at": manifest.created_at,
        "description": manifest.description,
    }


@app.get("/api/versions")
def list_versions() -> dict[str, Any]:
    """List all version manifests from the versions directories."""
    summaries = []
    for path in _find_manifests():
        try:
            m = load_manifest(path)
            summaries.append(_manifest_summary(m))
        except (OSError, KeyError, ValueError):
            continue
    return {"versions": summaries}


@app.post("/api/versions", status_code=201)
def create_version(request: CreateVersionRequest) -> dict[str, Any]:
    """Create a new agent version. If base is omitted, uses the default skills directory."""
    from agent.versioning.manifest import (
        AgentVersionManifest,
        RuntimeConfig,
        ModelConfig,
        EvolutionConfig,
        VersionStatus,
        current_git_commit,
        save_manifest,
    )
    from datetime import datetime, timezone
    import shutil

    versions_root = Path("agent_versions")
    candidate_dir = versions_root / request.name
    if candidate_dir.exists():
        raise HTTPException(status_code=409, detail=f"version '{request.name}' already exists")

    model_cfg = ModelConfig(
        provider=request.provider,
        model=request.model,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        base_url=request.base_url,
        api_key=request.api_key,
    )
    runtime_cfg = RuntimeConfig(
        git_commit=current_git_commit(),
        tot_enabled=request.tot_enabled,
        got_enabled=request.got_enabled,
        got_trigger_threshold=request.got_trigger_threshold,
    )
    evolution_cfg = EvolutionConfig(
        batch_dream_enabled=request.batch_dream_enabled,
    )

    if request.base:
        # Copy from base version, then override configs
        try:
            version_dir = create_agent_version(
                name=request.name,
                base=request.base,
                notes=request.notes,
            )
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail=f"base version '{request.base}' not found")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        # Override configs from request
        manifest = load_manifest(version_dir / "manifest.json")
        manifest.model = model_cfg
        manifest.runtime = runtime_cfg
        manifest.evolution = evolution_cfg
        save_manifest(manifest, version_dir / "manifest.json")
    else:
        # Create from default skills directory
        candidate_dir.mkdir(parents=True, exist_ok=True)
        src_skills = Path("skills")
        if src_skills.exists():
            shutil.copytree(src_skills, candidate_dir / "skills")
        else:
            (candidate_dir / "skills").mkdir(exist_ok=True)
        (candidate_dir / "memory").mkdir(exist_ok=True)
        manifest = AgentVersionManifest(
            version=request.name,
            base_version="",
            status=VersionStatus.CANDIDATE,
            runtime=runtime_cfg,
            model=model_cfg,
            evolution=evolution_cfg,
            created_at=datetime.now(timezone.utc).isoformat(),
            notes=[request.notes] if request.notes else [],
        )
        save_manifest(manifest, candidate_dir / "manifest.json")
        version_dir = candidate_dir

    manifest = load_manifest(version_dir / "manifest.json")
    return _manifest_summary(manifest)


@app.get("/api/versions/leaderboard")
def versions_leaderboard() -> dict[str, Any]:
    """Return the current leaderboard data under the versions namespace."""
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


@app.get("/api/versions/{version_id}")
def get_version(version_id: str) -> dict[str, Any]:
    """Load and return a specific version manifest."""
    path = _find_manifest_for_version(version_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"version '{version_id}' not found")
    try:
        manifest = load_manifest(path)
    except (OSError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"failed to load manifest: {exc}") from exc
    data = manifest.to_dict()
    return {
        **data,
        "version_id": manifest.version,
        "label": manifest.display_name or manifest.version,
        "skill_dir": manifest.paths.skills,
        "config": {
            "runtime": manifest.runtime.to_dict(),
            "evolution": manifest.evolution.to_dict(),
            "model": manifest.model.to_dict(),
            "paths": manifest.paths.to_dict(),
        },
        "metrics": manifest.evaluation,
    }


@app.post("/api/versions/{version_id}/promote")
def promote_version(version_id: str) -> dict[str, Any]:
    """Evaluate promotion eligibility for a version against the current validated baseline."""
    path = _find_manifest_for_version(version_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"version '{version_id}' not found")

    try:
        candidate_manifest = load_manifest(path)
    except (OSError, KeyError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"failed to load manifest: {exc}") from exc

    # Load leaderboard entries to find candidate and base scores
    leaderboard_entries: list[dict] = []
    for lb_path in _LEADERBOARD_PATHS:
        if lb_path.exists():
            try:
                raw = json.loads(lb_path.read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    leaderboard_entries = raw
                elif isinstance(raw, dict) and "entries" in raw:
                    leaderboard_entries = raw["entries"]
                break
            except (OSError, json.JSONDecodeError):
                continue

    # Find candidate entry by version name
    candidate_entry_dict = None
    for entry in leaderboard_entries:
        if entry.get("version") == version_id or entry.get("version") == candidate_manifest.version:
            candidate_entry_dict = entry
            break

    if candidate_entry_dict is None:
        raise HTTPException(
            status_code=404,
            detail=f"no leaderboard entry found for version '{version_id}'",
        )

    # Find base version entry (validated version or base_version from manifest)
    base_version = candidate_manifest.base_version
    base_entry_dict = None
    for entry in leaderboard_entries:
        if entry.get("version") == base_version:
            base_entry_dict = entry
            break

    if base_entry_dict is None:
        raise HTTPException(
            status_code=404,
            detail=f"no leaderboard entry found for base version '{base_version}'",
        )

    def _dict_to_entry(d: dict) -> LeaderboardEntry:
        return LeaderboardEntry(
            version=d.get("version", ""),
            games=d.get("games", 0),
            werewolf_win_rate=d.get("werewolf_win_rate", 0.0),
            villager_win_rate=d.get("villager_win_rate", 0.0),
            avg_days=d.get("avg_days", 0.0),
            avg_score=d.get("avg_score", 0.0),
            avg_speech_score=d.get("avg_speech_score", 0.0),
            avg_vote_score=d.get("avg_vote_score", 0.0),
            avg_skill_score=d.get("avg_skill_score", 0.0),
            avg_confidence=d.get("avg_confidence", 0.0),
            fallback_rate=d.get("fallback_rate", 0.0),
            vote_accuracy=d.get("vote_accuracy", 0.0),
            skill_accuracy=d.get("skill_accuracy", 0.0),
            policy_adjusted_rate=d.get("policy_adjusted_rate", 0.0),
            bad_case_count=d.get("bad_case_count", 0.0),
            turning_point_quality=d.get("turning_point_quality", 0.0),
            tot_usage_rate=d.get("tot_usage_rate", 0.0),
            got_trigger_count=d.get("got_trigger_count", 0),
            got_failure_count=d.get("got_failure_count", 0),
            information_score=d.get("information_score", 0.0),
            cooperation_score=d.get("cooperation_score", 0.0),
            by_role=d.get("by_role", {}),
            notes=d.get("notes", ""),
            run_ids=d.get("run_ids", []),
        )

    verdict = evaluate_promotion(
        candidate=_dict_to_entry(candidate_entry_dict),
        base=_dict_to_entry(base_entry_dict),
    )
    return {
        "version_id": version_id,
        "passed": verdict.promoted,
        "promoted": verdict.promoted,
        "score": verdict.metrics.get("score_improvement", 0.0),
        "reasons": verdict.reasons,
        "metrics": verdict.metrics,
        "details": verdict.metrics,
    }


# ── Selfplay Batch Runs ──────────────────────────────────────────────────────


@app.post("/api/selfplay", status_code=201)
async def start_selfplay(request: SelfplayRequest | None = None) -> dict[str, Any]:
    """Start a batch selfplay run in the background. Returns the run_id."""
    if request is None:
        request = SelfplayRequest()
    agent_version = request.agent_version or "agent"
    skill_dir = request.skill_dir
    model_name: str | None = None
    temperature = 0.2
    if request.agent_version:
        manifest_path = _find_manifest_for_version(request.agent_version)
        if manifest_path is None:
            raise HTTPException(
                status_code=404,
                detail=f"agent version '{request.agent_version}' not found",
            )
        manifest = load_manifest(manifest_path)
        skill_dir = str(resolve_manifest_path(manifest_path, manifest.paths.skills))
        model_name = manifest.model.model or None
        temperature = manifest.model.temperature
    run = await selfplay_manager.start_run(
        num_games=request.num_games,
        agent_version=agent_version,
        skill_dir=skill_dir,
        model_name=model_name,
        temperature=temperature,
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


# ── Evolution Runs ───────────────────────────────────────────────────────────


@app.post("/api/evolution", status_code=201)
async def start_evolution(request: EvolutionRequest) -> dict[str, Any]:
    """Start one self-evolution iteration from UI."""
    if _find_manifest_for_version(request.base_version) is None:
        raise HTTPException(
            status_code=404,
            detail=f"base version '{request.base_version}' not found",
        )
    if _find_manifest_for_version(request.candidate_version) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"candidate version '{request.candidate_version}' already exists",
        )
    run = await evolution_manager.start_run(
        base_version=request.base_version,
        candidate_version=request.candidate_version,
        training_games=request.training_games,
        battle_games=request.battle_games,
        training_seed_start=request.training_seed_start,
        battle_seed_start=request.battle_seed_start,
        max_days=request.max_days,
        enable_dream=request.enable_dream,
        enable_skill_proposals=request.enable_skill_proposals,
        auto_apply_skill_proposals=request.auto_apply_skill_proposals,
        min_score_improvement=request.min_score_improvement,
        max_win_rate_drop=request.max_win_rate_drop,
        notes=request.notes,
    )
    return run.snapshot()


@app.get("/api/evolution")
def list_evolution_runs() -> dict[str, Any]:
    return {"runs": evolution_manager.list_runs()}


@app.get("/api/evolution/{run_id}")
def get_evolution_run(run_id: str) -> dict[str, Any]:
    run = evolution_manager.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="evolution run not found")
    return run.snapshot()


# ── Mixed Version Battles ────────────────────────────────────────────────────


@app.post("/api/mixed-battles", status_code=201)
async def start_mixed_battle(request: MixedBattleRequest) -> dict[str, Any]:
    """Start a team-level mixed-version battle."""
    wolves_manifest = _find_manifest_for_version(request.wolves_version)
    if wolves_manifest is None:
        raise HTTPException(
            status_code=404,
            detail=f"wolves version '{request.wolves_version}' not found",
        )
    villagers_manifest = _find_manifest_for_version(request.villagers_version)
    if villagers_manifest is None:
        raise HTTPException(
            status_code=404,
            detail=f"villagers version '{request.villagers_version}' not found",
        )
    run = await mixed_battle_manager.start_run(
        wolves_manifest_path=wolves_manifest,
        villagers_manifest_path=villagers_manifest,
        games_per_side=request.games_per_side,
        seed_start=request.seed_start,
        max_days=request.max_days,
        enable_review=request.enable_review,
    )
    return run.snapshot()


@app.get("/api/mixed-battles")
def list_mixed_battles() -> dict[str, Any]:
    return {"runs": mixed_battle_manager.list_runs()}


@app.get("/api/mixed-battles/{run_id}")
def get_mixed_battle(run_id: str) -> dict[str, Any]:
    run = mixed_battle_manager.get_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="mixed battle run not found")
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
